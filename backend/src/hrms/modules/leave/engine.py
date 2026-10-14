"""
Leave accounting engine — the single authoritative writer for the monthly ledger
and immutable transaction journal.

Hard rules (enforced by architecture & review):
1. leave_monthly_ledger and leave_balance_transactions are only ever mutated here.
2. Every mutation acquires lock_leave_bucket(session, tenant_id, employment_id, bucket_id).
3. The forward cascade (recalculate_closing_and_cascade) ensures ledger continuity:
   row[i+1].opening == row[i].closing across calendar order.
"""

from __future__ import annotations

import math
from datetime import date
from fractions import Fraction
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import and_, col, or_, select

from hrms.core.datetime_utils import now_utc
from hrms.core.locking import lock_resource
from hrms.modules.leave.models import (
    LeaveBalanceTransaction,
    LeaveMonthlyLedger,
    LeaveTransactionType,
)


def compute_fy_year(calendar_year: int, calendar_month: int, fy_start_month: int = 4) -> int:
    """
    Compute financial year label from calendar year and month.
    For April start (4):
      - 2026-04 -> 2026 (FY 2026-27)
      - 2027-03 -> 2026 (FY 2026-27)
      - 2027-04 -> 2027 (FY 2027-28)
    For January start (1):
      - 2026-01 -> 2026
    """
    if calendar_month >= fy_start_month:
        return calendar_year
    return calendar_year - 1


async def lock_leave_bucket(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
    bucket_id: UUID,
) -> None:
    """Individual writers share the tenant gate; bulk writers hold it exclusively."""
    transaction = _ledger_transaction(session)
    bulk = session.info.get("leave_bulk_transactions", {})
    if transaction is not None and bulk.get(tenant_id) is transaction:
        return  # This exact transaction already holds the exclusive tenant gate.
    await session.execute(
        text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:key,0))"),
        {"key": f"{tenant_id}:leave-ledger"},
    )
    await lock_resource(session, tenant_id, f"leave:{employment_id}:{bucket_id}")


def _ledger_transaction(session: AsyncSession):
    # Savepoint rollback releases its advisory locks; never cache their ownership on
    # the outer transaction. A new transaction must acquire its own gate too.
    return session.sync_session.get_nested_transaction() or session.sync_session.get_transaction()


async def lock_bulk_ledger(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"{tenant_id}:leave-ledger"},
    )
    session.info.setdefault("leave_bulk_transactions", {})[tenant_id] = _ledger_transaction(session)


async def recalculate_closing_and_cascade(
    session: AsyncSession,
    tenant_id: UUID,
    row: LeaveMonthlyLedger,
) -> LeaveMonthlyLedger:
    """
    Recalculate row.closing = opening + accrued + granted + adjustment - taken - lapsed - encashed.
    Then, if a later row exists in calendar order, forward-cascade this closing
    into next_row.opening.
    """
    row.closing = (
        row.opening
        + row.accrued
        + row.granted
        + row.adjustment
        - row.taken
        - row.lapsed
        - row.encashed
    )
    session.add(row)
    await session.flush()

    # Forward cascade: find immediate next row in calendar order
    stmt = (
        select(LeaveMonthlyLedger)
        .where(LeaveMonthlyLedger.tenant_id == tenant_id)
        .where(LeaveMonthlyLedger.employment_id == row.employment_id)
        .where(LeaveMonthlyLedger.bucket_id == row.bucket_id)
        .where(
            or_(
                LeaveMonthlyLedger.calendar_year > row.calendar_year,
                and_(
                    LeaveMonthlyLedger.calendar_year == row.calendar_year,
                    LeaveMonthlyLedger.calendar_month > row.calendar_month,
                ),
            )
        )
        .order_by(
            col(LeaveMonthlyLedger.calendar_year).asc(),
            col(LeaveMonthlyLedger.calendar_month).asc(),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    next_row = result.scalars().first()

    if next_row is not None and next_row.opening != row.closing:
        next_row.opening = row.closing
        await recalculate_closing_and_cascade(session, tenant_id, next_row)

    return row


async def get_or_create_ledger_row(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
    bucket_id: UUID,
    calendar_year: int,
    calendar_month: int,
    fy_start_month: int = 4,
    *,
    initial_opening: float | None = None,
) -> LeaveMonthlyLedger:
    """
    Get or create a ledger row for (employment, bucket, calendar_year, calendar_month).
    1. If exists: return it.
    2. Prior row lookup: greatest (year, month) strictly less than target in calendar order.
    3. opening = initial_opening if initial_opening is not None else (prior.closing if prior else 0)
    4. fy_year = compute_fy_year(calendar_year, calendar_month, fy_start_month)
    5. insert new_row (closing = opening)
    6. Forward cascade: if next row exists and next_row.opening != new_row.closing,
       propagate forward.
    """
    # 1. Existing row check
    stmt = (
        select(LeaveMonthlyLedger)
        .where(LeaveMonthlyLedger.tenant_id == tenant_id)
        .where(LeaveMonthlyLedger.employment_id == employment_id)
        .where(LeaveMonthlyLedger.bucket_id == bucket_id)
        .where(LeaveMonthlyLedger.calendar_year == calendar_year)
        .where(LeaveMonthlyLedger.calendar_month == calendar_month)
    )
    existing = (await session.execute(stmt)).scalars().first()
    if existing:
        return existing

    # 2. Prior row lookup strictly less than target
    prior_stmt = (
        select(LeaveMonthlyLedger)
        .where(LeaveMonthlyLedger.tenant_id == tenant_id)
        .where(LeaveMonthlyLedger.employment_id == employment_id)
        .where(LeaveMonthlyLedger.bucket_id == bucket_id)
        .where(
            or_(
                LeaveMonthlyLedger.calendar_year < calendar_year,
                and_(
                    LeaveMonthlyLedger.calendar_year == calendar_year,
                    LeaveMonthlyLedger.calendar_month < calendar_month,
                ),
            )
        )
        .order_by(
            col(LeaveMonthlyLedger.calendar_year).desc(),
            col(LeaveMonthlyLedger.calendar_month).desc(),
        )
        .limit(1)
    )
    prior = (await session.execute(prior_stmt)).scalars().first()

    opening = initial_opening if initial_opening is not None else (prior.closing if prior else 0.0)
    fy_year = compute_fy_year(calendar_year, calendar_month, fy_start_month)

    new_row = LeaveMonthlyLedger(
        tenant_id=tenant_id,
        id=uuid4(),
        recorded_at=now_utc(),
        employment_id=employment_id,
        bucket_id=bucket_id,
        calendar_year=calendar_year,
        calendar_month=calendar_month,
        fy_year=fy_year,
        opening=opening,
        accrued=0.0,
        granted=0.0,
        held=0.0,
        adjustment=0.0,
        taken=0.0,
        lapsed=0.0,
        encashed=0.0,
        closing=opening,
    )
    session.add(new_row)
    await session.flush()

    # 6. Forward cascade if a next row already exists
    next_stmt = (
        select(LeaveMonthlyLedger)
        .where(LeaveMonthlyLedger.tenant_id == tenant_id)
        .where(LeaveMonthlyLedger.employment_id == employment_id)
        .where(LeaveMonthlyLedger.bucket_id == bucket_id)
        .where(
            or_(
                LeaveMonthlyLedger.calendar_year > calendar_year,
                and_(
                    LeaveMonthlyLedger.calendar_year == calendar_year,
                    LeaveMonthlyLedger.calendar_month > calendar_month,
                ),
            )
        )
        .order_by(
            col(LeaveMonthlyLedger.calendar_year).asc(),
            col(LeaveMonthlyLedger.calendar_month).asc(),
        )
        .limit(1)
    )
    next_row = (await session.execute(next_stmt)).scalars().first()
    if next_row is not None and next_row.opening != new_row.closing:
        next_row.opening = new_row.closing
        await recalculate_closing_and_cascade(session, tenant_id, next_row)

    return new_row


async def record_transaction(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    employment_id: UUID,
    bucket_id: UUID,
    leave_type_id: UUID | None = None,
    transaction_type: LeaveTransactionType | str,
    quantity: float,
    effective_date: date,
    reason: str | None = None,
    reference_id: UUID | None = None,
    reference_type: str | None = None,
    recorded_by: UUID,
    approved_by: UUID | None = None,
    fy_start_month: int = 4,
    initial_opening: float | None = None,
) -> tuple[LeaveBalanceTransaction, LeaveMonthlyLedger]:
    """
    Atomic transaction record + ledger mutation under (employment, bucket) advisory lock.
    """
    await lock_leave_bucket(session, tenant_id, employment_id, bucket_id)

    target_year = effective_date.year
    target_month = effective_date.month

    ledger_row = await get_or_create_ledger_row(
        session,
        tenant_id,
        employment_id,
        bucket_id,
        target_year,
        target_month,
        fy_start_month=fy_start_month,
        initial_opening=initial_opening,
    )

    previous_balance = ledger_row.closing - ledger_row.held

    tt = LeaveTransactionType(transaction_type)
    if tt == LeaveTransactionType.HOLD:
        ledger_row.held += quantity
    elif tt == LeaveTransactionType.RELEASE:
        ledger_row.held = max(0.0, ledger_row.held - quantity)
    elif tt == LeaveTransactionType.LEAVE_TAKEN:
        ledger_row.held = max(0.0, ledger_row.held - quantity)
        ledger_row.taken += quantity
    elif tt == LeaveTransactionType.LEAVE_REVERSED:
        ledger_row.taken = max(0.0, ledger_row.taken - quantity)
    elif tt == LeaveTransactionType.OPENING:
        ledger_row.opening += quantity
    elif tt == LeaveTransactionType.ACCRUAL:
        ledger_row.accrued += quantity
    elif tt == LeaveTransactionType.GRANT:
        ledger_row.granted += quantity
    elif tt == LeaveTransactionType.ADJUSTMENT:
        ledger_row.adjustment += quantity
    elif tt == LeaveTransactionType.LAPSE:
        ledger_row.lapsed += abs(quantity)
    elif tt == LeaveTransactionType.ENCASHMENT:
        ledger_row.encashed += abs(quantity)
    elif tt == LeaveTransactionType.CARRY_FORWARD:
        ledger_row.opening += quantity

    await recalculate_closing_and_cascade(session, tenant_id, ledger_row)

    new_balance = ledger_row.closing - ledger_row.held

    tx = LeaveBalanceTransaction(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=employment_id,
        bucket_id=bucket_id,
        leave_type_id=leave_type_id,
        transaction_type=tt.value,
        quantity=quantity,
        previous_balance=previous_balance,
        new_balance=new_balance,
        effective_date=effective_date,
        reason=reason,
        reference_id=reference_id,
        reference_type=reference_type,
        recorded_by=recorded_by,
        approved_by=approved_by,
        recorded_at=now_utc(),
    )
    session.add(tx)
    await session.flush()

    return tx, ledger_row


def half_days_earned(days_per_year: float, months: int) -> float:
    """
    Leave earned after `months` monthly accruals of a yearly entitlement, rounded down to a
    half day (DB-D2: leave is only ever taken or held in whole or half days). Computed with
    exact fractions, so 12 months of any entitlement add up to exactly that entitlement.
    """
    earned = Fraction(str(days_per_year)) * months / 12
    return float(math.floor(earned * 2)) / 2


def monthly_credit(days_per_year: float, months_before: int) -> float:
    """
    This month's accrual after `months_before` earlier ones in the financial year: whatever
    makes the running total equal half_days_earned. 25 days a year credits 2, 2, 2, 2, 2, 2.5,
    2, 2, 2, 2, 2, 2.5; small entitlements credit 0 in some months (that month still counts).
    """
    return half_days_earned(days_per_year, months_before + 1) - half_days_earned(
        days_per_year, months_before
    )


async def record_accruals(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    bucket_id: UUID,
    leave_type_id: UUID,
    credits: list[tuple[UUID, float, int]],
    effective_date: date,
    reference_type: str,
    recorded_by: UUID,
) -> None:
    """
    record_transaction(ACCRUAL) for many employees in one bucket, with the same result:
    the same writer exclusion, the same ledger rows and closing arithmetic, the same journal
    rows. `credits` is (employment_id, quantity, fy_start_month), in the order to lock.

    The set-based path covers every employee with no ledger row after the target month
    — a regular monthly run, where nothing needs to cascade forward. Anyone who does have
    a later row (a back-dated run) goes through record_transaction itself, so the forward
    cascade lives in exactly one place.

    The ledger rows are written with SQL, not through the ORM: the caller must not already
    hold loaded LeaveMonthlyLedger objects for these (employment, bucket, month) rows.
    """
    if not credits:
        return
    year, month = effective_date.year, effective_date.month
    tid = str(tenant_id)
    await lock_bulk_ledger(session, tenant_id)
    ids = [str(emp) for emp, _, _ in credits]
    later = {
        UUID(str(r[0]))
        for r in await session.execute(
            text("""
                SELECT DISTINCT employment_id FROM leave_monthly_ledger
                WHERE tenant_id = CAST(:tid AS uuid) AND bucket_id = CAST(:bucket AS uuid)
                  AND employment_id = ANY(CAST(:ids AS uuid[]))
                  AND (calendar_year, calendar_month) > (:y, :m)
            """),
            {"tid": tid, "bucket": str(bucket_id), "ids": ids, "y": year, "m": month},
        )
    }
    bulk = [c for c in credits if c[0] not in later]
    for emp, quantity, fy_start_month in credits:
        if emp in later:
            await record_transaction(
                session,
                tenant_id,
                employment_id=emp,
                bucket_id=bucket_id,
                leave_type_id=leave_type_id,
                transaction_type=LeaveTransactionType.ACCRUAL,
                quantity=quantity,
                effective_date=effective_date,
                reference_type=reference_type,
                recorded_by=recorded_by,
                fy_start_month=fy_start_month,
            )
    if not bulk:
        return
    # Flush ORM state so the SQL below sees any rows record_transaction just wrote.
    await session.flush()
    emps = [str(emp) for emp, _, _ in bulk]
    params = {"tid": tid, "bucket": str(bucket_id), "y": year, "m": month, "emps": emps}
    # Missing target rows open at the prior row's closing (get_or_create_ledger_row).
    await session.execute(
        text("""
            INSERT INTO leave_monthly_ledger (tenant_id, id, recorded_at, employment_id,
                bucket_id, calendar_year, calendar_month, fy_year, opening, accrued, granted,
                held, adjustment, taken, lapsed, encashed, closing)
            SELECT CAST(:tid AS uuid), gen_random_uuid(), now(), c.emp, CAST(:bucket AS uuid),
                   :y, :m, c.fy_year, COALESCE(p.closing, 0), 0, 0, 0, 0, 0, 0, 0,
                   COALESCE(p.closing, 0)
            FROM unnest(CAST(:emps AS uuid[]), CAST(:fy AS int[])) AS c(emp, fy_year)
            LEFT JOIN LATERAL (
                SELECT closing FROM leave_monthly_ledger
                WHERE tenant_id = CAST(:tid AS uuid) AND employment_id = c.emp
                  AND bucket_id = CAST(:bucket AS uuid)
                  AND (calendar_year, calendar_month) < (:y, :m)
                ORDER BY calendar_year DESC, calendar_month DESC LIMIT 1
            ) p ON true
            ON CONFLICT (tenant_id, employment_id, bucket_id, calendar_year, calendar_month)
            DO NOTHING
        """),
        {**params, "fy": [compute_fy_year(year, month, fy) for _, _, fy in bulk]},
    )
    # accrued += quantity, then closing recomputed term by term in recalculate_closing's
    # order, so the float result is identical to the one-at-a-time path.
    updated = await session.execute(
        text("""
            UPDATE leave_monthly_ledger l
            SET accrued = l.accrued + s.qty,
                closing = l.opening + (l.accrued + s.qty) + l.granted + l.adjustment
                          - l.taken - l.lapsed - l.encashed
            FROM (
                SELECT l2.id, c.qty, l2.closing AS old_closing
                FROM unnest(CAST(:emps AS uuid[]), CAST(:qty AS float8[])) AS c(emp, qty)
                JOIN leave_monthly_ledger l2
                  ON l2.tenant_id = CAST(:tid AS uuid) AND l2.employment_id = c.emp
                 AND l2.bucket_id = CAST(:bucket AS uuid)
                 AND l2.calendar_year = :y AND l2.calendar_month = :m
            ) s
            WHERE l.tenant_id = CAST(:tid AS uuid) AND l.id = s.id
            RETURNING l.employment_id, s.qty, s.old_closing - l.held, l.closing - l.held
        """),
        {**params, "qty": [q for _, q, _ in bulk]},
    )
    journal = updated.all()
    await session.execute(
        text("""
            INSERT INTO leave_balance_transactions (tenant_id, id, employment_id, bucket_id,
                leave_type_id, transaction_type, quantity, previous_balance, new_balance,
                effective_date, reference_type, recorded_by, recorded_at)
            SELECT CAST(:tid AS uuid), gen_random_uuid(), j.emp, CAST(:bucket AS uuid),
                   CAST(:lt AS uuid), 'ACCRUAL', j.qty, j.prev, j.new, :eff, :ref,
                   CAST(:by AS uuid), now()
            FROM unnest(CAST(:emps AS uuid[]), CAST(:qty AS float8[]),
                        CAST(:prev AS float8[]), CAST(:new AS float8[])) AS j(emp, qty, prev, new)
        """),
        {
            "tid": tid,
            "bucket": str(bucket_id),
            "lt": str(leave_type_id),
            "eff": effective_date,
            "ref": reference_type,
            "by": str(recorded_by),
            "emps": [str(r[0]) for r in journal],
            # The balances come back as numeric (Decimal); the array parameters are float8.
            "qty": [float(r[1]) for r in journal],
            "prev": [float(r[2]) for r in journal],
            "new": [float(r[3]) for r in journal],
        },
    )

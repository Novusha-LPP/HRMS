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

from datetime import date
from uuid import UUID, uuid4

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
    """Acquire transaction-level PostgreSQL advisory lock per (employment, bucket)."""
    await lock_resource(session, tenant_id, f"leave:{employment_id}:{bucket_id}")


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

"""Unused leave when someone leaves (docs/REJOIN_DEVELOPMENT_PLAN.md, R2).

A company can say, per leave type, what happens to the unused balance on separation: LAPSE it,
ENCASH it (up to a cap; the rest lapses), or HOLD it (for a number of days, or indefinitely) so
that a quick return can still get it back. Every outcome is a ledger entry; nothing is edited.

With no rule in force nothing happens at all, which is how every company behaves today.

`plan_settlement` only reads and is what the preview shows; `settle_on_separation` writes the
same plan and is safe to repeat: one settlement row per (stint, balance) stops a second run.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlmodel import col, select

from hrms.core.authz import SYSTEM_ACTOR
from hrms.core.datetime_utils import now_utc
from hrms.core.metrics import HELD_LEAVE_RESOLVED, SEPARATION_SETTLEMENTS
from hrms.modules.leave.engine import record_transaction
from hrms.modules.leave.models import (
    LeaveBalanceBucket,
    LeaveEncashment,
    LeaveMonthlyLedger,
    LeaveSeparationRule,
    LeaveSeparationSettlement,
    LeaveTransactionType,
    LeaveType,
    LeaveTypeBucketMapping,
    SeparationAction,
    SettlementResolution,
)
from hrms.modules.leave.policy_resolver import resolve_employee_fy_start_month
from hrms.modules.people.models import Employment, EmploymentSpell, EmploymentState


@dataclass
class PlannedItem:
    leave_type_id: UUID
    leave_type_name: str
    bucket_id: UUID
    days: float
    action: str
    encash_days: float = 0.0
    lapse_days: float = 0.0
    held_days: float = 0.0
    hold_expires_on: date | None = None
    rule_id: UUID | None = None
    note: str | None = None


def _half(days: float) -> float:
    """Balances are whole or half days; keep arithmetic from drifting."""
    return round(days * 2) / 2


def pick_rule(
    rules: list[LeaveSeparationRule],
    legal_entity_id: UUID | None,
    leave_type_id: UUID,
    on: date,
) -> LeaveSeparationRule | None:
    """The most specific rule in force on `on`: company and type, then company, then type, then
    neither. Among equals the latest start date wins."""
    best: tuple[int, date] | None = None
    chosen: LeaveSeparationRule | None = None
    for rule in rules:
        if rule.archived_at is not None or rule.effective_from > on:
            continue
        if rule.legal_entity_id not in (None, legal_entity_id):
            continue
        if rule.leave_type_id not in (None, leave_type_id):
            continue
        rank = (2 if rule.legal_entity_id else 0) + (1 if rule.leave_type_id else 0)
        key = (rank, rule.effective_from)
        if best is None or key > best:
            best, chosen = key, rule
    return chosen


async def _held_balance(session, tenant_id: UUID, employment_id: UUID, bucket_id: UUID, on: date):
    """The unused balance on `on`, read without creating anything."""
    row = (
        (
            await session.execute(
                select(LeaveMonthlyLedger)
                .where(col(LeaveMonthlyLedger.tenant_id) == tenant_id)
                .where(col(LeaveMonthlyLedger.employment_id) == employment_id)
                .where(col(LeaveMonthlyLedger.bucket_id) == bucket_id)
                .where(
                    (col(LeaveMonthlyLedger.calendar_year) < on.year)
                    | (
                        (col(LeaveMonthlyLedger.calendar_year) == on.year)
                        & (col(LeaveMonthlyLedger.calendar_month) <= on.month)
                    )
                )
                .order_by(
                    col(LeaveMonthlyLedger.calendar_year).desc(),
                    col(LeaveMonthlyLedger.calendar_month).desc(),
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return 0.0 if row is None else _half(row.closing - row.held)


async def plan_settlement(
    session, tenant_id: UUID, emp: Employment, as_of: date
) -> list[PlannedItem]:
    """What separating `emp` on `as_of` would do with their unused leave. Writes nothing."""
    rules = list(
        (
            await session.execute(
                select(LeaveSeparationRule)
                .where(col(LeaveSeparationRule.tenant_id) == tenant_id)
                .where(col(LeaveSeparationRule.archived_at).is_(None))
            )
        ).scalars()
    )
    if not rules:
        return []
    pairs = (
        await session.execute(
            select(LeaveType, LeaveTypeBucketMapping, LeaveBalanceBucket)
            .join(
                LeaveTypeBucketMapping,
                (col(LeaveTypeBucketMapping.tenant_id) == col(LeaveType.tenant_id))
                & (col(LeaveTypeBucketMapping.leave_type_id) == col(LeaveType.id)),
            )
            .join(
                LeaveBalanceBucket,
                (col(LeaveBalanceBucket.tenant_id) == col(LeaveTypeBucketMapping.tenant_id))
                & (col(LeaveBalanceBucket.id) == col(LeaveTypeBucketMapping.bucket_id)),
            )
            .where(col(LeaveType.tenant_id) == tenant_id)
            .where(col(LeaveType.archived_at).is_(None))
            .where(col(LeaveBalanceBucket.is_unlimited).is_(False))
            .order_by(col(LeaveType.name))
        )
    ).all()

    items: list[PlannedItem] = []
    seen_buckets: set[UUID] = set()
    for leave_type, _mapping, bucket in pairs:
        if bucket.id in seen_buckets:  # several types can share one balance: settle it once
            continue
        seen_buckets.add(bucket.id)
        rule = pick_rule(rules, emp.legal_entity_id, leave_type.id, as_of)
        if rule is None:
            continue
        days = await _held_balance(session, tenant_id, emp.id, bucket.id, as_of)
        if days <= 0:
            continue
        item = PlannedItem(
            leave_type_id=leave_type.id,
            leave_type_name=leave_type.name,
            bucket_id=bucket.id,
            days=days,
            action=rule.on_separation,
            rule_id=rule.id,
        )
        if rule.on_separation == SeparationAction.LAPSE:
            item.lapse_days = days
        elif rule.on_separation == SeparationAction.ENCASH:
            if not leave_type.encashable:
                # Encashment is only for types HR has marked encashable; leave the rest held.
                item.action = SeparationAction.HOLD
                item.held_days = days
                item.note = f"{leave_type.name} is not marked encashable, so it is held"
            else:
                cap = rule.max_encash_days
                item.encash_days = days if cap is None else min(days, _half(float(cap)))
                item.lapse_days = _half(days - item.encash_days)
        else:
            item.held_days = days
            if rule.hold_days is not None:
                item.hold_expires_on = as_of + timedelta(days=rule.hold_days)
        items.append(item)
    return items


async def settle_on_separation(
    session,
    tenant_id: UUID,
    emp: Employment,
    spell: EmploymentSpell,
    as_of: date,
    actor: UUID | None = None,
) -> list[LeaveSeparationSettlement]:
    """Apply `plan_settlement` for the stint that just ended. Repeating it changes nothing."""
    plan = await plan_settlement(session, tenant_id, emp, as_of)
    if not plan:
        return []
    recorded_by = actor or SYSTEM_ACTOR
    done = {
        s.bucket_id
        for s in (
            await session.execute(
                select(LeaveSeparationSettlement)
                .where(col(LeaveSeparationSettlement.tenant_id) == tenant_id)
                .where(col(LeaveSeparationSettlement.spell_id) == spell.id)
            )
        ).scalars()
    }
    fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, emp.id)
    settlements: list[LeaveSeparationSettlement] = []
    for item in plan:
        if item.bucket_id in done:
            continue
        tx_id: UUID | None = None
        reason = f"Separation on {as_of.isoformat()}"
        if item.encash_days > 0:
            encashment = LeaveEncashment(
                tenant_id=tenant_id,
                id=uuid4(),
                employment_id=emp.id,
                leave_type_id=item.leave_type_id,
                days=item.encash_days,
                effective_date=as_of,
                notes=reason,
                processed_by=None,
                recorded_at=now_utc(),
            )
            session.add(encashment)
            await session.flush()
            tx, _ = await record_transaction(
                session,
                tenant_id,
                employment_id=emp.id,
                bucket_id=item.bucket_id,
                leave_type_id=item.leave_type_id,
                transaction_type=LeaveTransactionType.ENCASHMENT,
                quantity=item.encash_days,
                effective_date=as_of,
                reason=reason,
                reference_id=encashment.id,
                reference_type="SEPARATION",
                recorded_by=recorded_by,
                fy_start_month=fy_start_month,
            )
            tx_id = tx.id
        if item.lapse_days > 0:
            tx, _ = await record_transaction(
                session,
                tenant_id,
                employment_id=emp.id,
                bucket_id=item.bucket_id,
                leave_type_id=item.leave_type_id,
                transaction_type=LeaveTransactionType.LAPSE,
                quantity=item.lapse_days,
                effective_date=as_of,
                reason=reason,
                reference_id=spell.id,
                reference_type="SEPARATION",
                recorded_by=recorded_by,
                fy_start_month=fy_start_month,
            )
            tx_id = tx_id or tx.id
        settlement = LeaveSeparationSettlement(
            tenant_id=tenant_id,
            id=uuid4(),
            employment_id=emp.id,
            spell_id=spell.id,
            leave_type_id=item.leave_type_id,
            bucket_id=item.bucket_id,
            days=item.days,
            encashed_days=item.encash_days,
            lapsed_days=item.lapse_days,
            action=item.action,
            settled_on=as_of,
            balance_transaction_id=tx_id,
            hold_expires_on=item.hold_expires_on,
            created_by=actor,
        )
        session.add(settlement)
        settlements.append(settlement)
        SEPARATION_SETTLEMENTS.labels(item.action).inc()
    await session.flush()
    return settlements


async def resolve_holds(session, tenant_id: UUID, today: date) -> dict[str, int]:
    """Close held balances that are due: lapse them if the person is still gone, or mark them
    restored if they have rejoined. Safe to run every day."""
    due = list(
        (
            await session.execute(
                select(LeaveSeparationSettlement, Employment)
                .join(
                    Employment,
                    (col(Employment.tenant_id) == col(LeaveSeparationSettlement.tenant_id))
                    & (col(Employment.id) == col(LeaveSeparationSettlement.employment_id)),
                )
                .where(col(LeaveSeparationSettlement.tenant_id) == tenant_id)
                .where(col(LeaveSeparationSettlement.action) == SeparationAction.HOLD)
                .where(col(LeaveSeparationSettlement.resolution).is_(None))
            )
        ).all()
    )
    counts = {"lapsed": 0, "restored": 0}
    for settlement, emp in due:
        if emp.employment_state != EmploymentState.SEPARATED:
            settlement.resolution = SettlementResolution.RESTORED
            settlement.resolved_on = today
            session.add(settlement)
            counts["restored"] += 1
            HELD_LEAVE_RESOLVED.labels("restored").inc()
            continue
        if settlement.hold_expires_on is None or settlement.hold_expires_on > today:
            continue
        days = await _held_balance(session, tenant_id, emp.id, settlement.bucket_id, today)
        days = min(days, _half(settlement.days))
        if days > 0:
            fy_start_month = await resolve_employee_fy_start_month(session, tenant_id, emp.id)
            tx, _ = await record_transaction(
                session,
                tenant_id,
                employment_id=emp.id,
                bucket_id=settlement.bucket_id,
                leave_type_id=settlement.leave_type_id,
                transaction_type=LeaveTransactionType.LAPSE,
                quantity=days,
                effective_date=today,
                reason=f"Held leave lapsed after separation on {settlement.settled_on}",
                reference_id=settlement.spell_id,
                reference_type="SEPARATION",
                recorded_by=SYSTEM_ACTOR,
                fy_start_month=fy_start_month,
            )
            settlement.balance_transaction_id = settlement.balance_transaction_id or tx.id
        settlement.lapsed_days = _half(settlement.lapsed_days + days)
        settlement.resolution = SettlementResolution.LAPSED
        settlement.resolved_on = today
        session.add(settlement)
        counts["lapsed"] += 1
        HELD_LEAVE_RESOLVED.labels("lapsed").inc()
    await session.flush()
    return counts

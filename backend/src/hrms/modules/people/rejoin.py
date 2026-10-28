"""Rejoining: continue earlier service and leave, or start fresh.

Design: docs/REJOIN_DEVELOPMENT_PLAN.md, R3.

`decide` works out what a rejoin on a date would do. It is the one place the rules live, so the
preview HR sees, the check when the action is entered, and the change when it is applied agree.
`apply_rejoin` makes the decision happen.

* CONTINUE keeps earlier service. Leave that was held at separation is restored; leave that was
  encashed or lapsed stays gone.
* FRESH starts over: whatever unused leave is left lapses (as ledger entries) and service for
  leave eligibility restarts from the rejoin date.

A company with no policy continues, with no limit on the break: how rejoining has always worked.
"""

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlmodel import col, select

from hrms.core.authz import SYSTEM_ACTOR
from hrms.core.metrics import REJOINS
from hrms.modules.leave.engine import record_transaction
from hrms.modules.leave.models import (
    LeaveBalanceBucket,
    LeaveMonthlyLedger,
    LeaveSeparationSettlement,
    LeaveTransactionType,
    LeaveType,
    LeaveTypeBucketMapping,
    SeparationAction,
    SettlementResolution,
)
from hrms.modules.leave.policy_resolver import resolve_employee_fy_start_month
from hrms.modules.leave.separation import _half
from hrms.modules.people import spells
from hrms.modules.people.models import (
    Employment,
    EmploymentSpell,
    RejoinMode,
    RejoinPolicy,
    RejoinRecord,
)


class RejoinChoice(BaseModel):
    """What HR decides when someone rejoins. Everything is optional: leave it out and the
    company's default applies."""

    mode: RejoinMode | None = Field(
        default=None,
        description="CONTINUE keeps earlier service and held leave; FRESH starts over.",
    )
    break_condoned: bool = Field(
        default=False,
        description="HR accepts the break as not interrupting service. Needed to continue after "
        "a break longer than the company allows.",
    )
    reason: str | None = Field(default=None, max_length=300)
    gratuity_paid_at_exit: bool | None = Field(
        default=None,
        description="Whether gratuity was paid when they left. If it was, service restarts.",
    )


@dataclass
class LeaveEffect:
    leave_type_id: UUID
    leave_type_name: str
    bucket_id: UUID
    days: float
    outcome: str  # KEPT | LAPSE


@dataclass
class RejoinDecision:
    mode: RejoinMode
    left_on: date | None
    rejoin_on: date
    gap_days: int | None
    default_mode: RejoinMode
    force_fresh_after_days: int | None
    gratuity_paid: bool | None
    break_condoned: bool
    reason: str | None
    automatic: bool  # the mode was chosen by the company's rules, not by HR
    blocked: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    leave: list[LeaveEffect] = field(default_factory=list)

    @property
    def allowed_modes(self) -> list[str]:
        modes = [RejoinMode.FRESH.value]
        if not self._continue_blocked():
            modes.insert(0, RejoinMode.CONTINUE.value)
        return modes

    def _continue_blocked(self) -> bool:
        if self.gratuity_paid:
            return True
        over = (
            self.force_fresh_after_days is not None
            and self.gap_days is not None
            and self.gap_days > self.force_fresh_after_days
        )
        return over and not (self.break_condoned and (self.reason or "").strip() != "")


def pick_policy(
    policies: list[RejoinPolicy], legal_entity_id: UUID | None, on: date
) -> RejoinPolicy | None:
    """The company's own policy in force on `on`, else the one for every company."""
    best: tuple[int, date] | None = None
    chosen: RejoinPolicy | None = None
    for policy in policies:
        if policy.archived_at is not None or policy.effective_from > on:
            continue
        if policy.legal_entity_id not in (None, legal_entity_id):
            continue
        key = (1 if policy.legal_entity_id else 0, policy.effective_from)
        if best is None or key > best:
            best, chosen = key, policy
    return chosen


async def _policy(session, tenant_id: UUID, emp: Employment, on: date) -> RejoinPolicy | None:
    rows = (
        await session.execute(
            select(RejoinPolicy)
            .where(col(RejoinPolicy.tenant_id) == tenant_id)
            .where(col(RejoinPolicy.archived_at).is_(None))
        )
    ).scalars()
    return pick_policy(list(rows), emp.legal_entity_id, on)


async def _last_spell(session, tenant_id: UUID, emp: Employment) -> EmploymentSpell | None:
    return (
        (
            await session.execute(
                select(EmploymentSpell)
                .where(col(EmploymentSpell.tenant_id) == tenant_id)
                .where(col(EmploymentSpell.employment_id) == emp.id)
                .where(col(EmploymentSpell.spell_no) == emp.current_spell_no)
            )
        )
        .scalars()
        .first()
    )


async def _balances(session, tenant_id: UUID, emp: Employment, on: date) -> list[LeaveEffect]:
    """Every unused balance the person still has, by leave type, with nothing created."""
    pairs = (
        await session.execute(
            select(LeaveType, LeaveBalanceBucket)
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
    effects: list[LeaveEffect] = []
    seen: set[UUID] = set()
    for leave_type, bucket in pairs:
        if bucket.id in seen:
            continue
        seen.add(bucket.id)
        row = (
            (
                await session.execute(
                    select(LeaveMonthlyLedger)
                    .where(col(LeaveMonthlyLedger.tenant_id) == tenant_id)
                    .where(col(LeaveMonthlyLedger.employment_id) == emp.id)
                    .where(col(LeaveMonthlyLedger.bucket_id) == bucket.id)
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
        days = 0.0 if row is None else _half(row.closing - row.held)
        if days > 0:
            effects.append(LeaveEffect(leave_type.id, leave_type.name, bucket.id, days, "KEPT"))
    return effects


async def decide(
    session,
    tenant_id: UUID,
    emp: Employment,
    rejoin_on: date,
    choice: RejoinChoice | None = None,
    *,
    left_on: date | None = None,
    strict: bool = True,
) -> RejoinDecision:
    """What rejoining on `rejoin_on` would do. With strict=True an invalid choice raises 422;
    with strict=False (the preview) the problems come back in `blocked`."""
    choice = choice or RejoinChoice()
    left = left_on if left_on is not None else emp.separation_date
    gap = (rejoin_on - left).days if left is not None else None
    policy = await _policy(session, tenant_id, emp, rejoin_on)
    default = RejoinMode(policy.default_mode) if policy else RejoinMode.CONTINUE
    last = await _last_spell(session, tenant_id, emp)
    gratuity = choice.gratuity_paid_at_exit
    if gratuity is None and last is not None:
        gratuity = last.gratuity_paid
    decision = RejoinDecision(
        mode=default,
        left_on=left,
        rejoin_on=rejoin_on,
        gap_days=gap,
        default_mode=default,
        force_fresh_after_days=policy.force_fresh_after_days if policy else None,
        gratuity_paid=gratuity,
        break_condoned=choice.break_condoned,
        reason=(choice.reason or "").strip() or None,
        automatic=choice.mode is None,
    )
    if gap is not None and gap < 0:
        decision.blocked.append("The rejoin date is before they left.")
    if choice.mode is not None:
        decision.mode = choice.mode
    elif decision._continue_blocked():
        decision.mode = RejoinMode.FRESH  # the company's rules leave only one way to rejoin
        why = (
            "gratuity was paid when they left"
            if gratuity
            else f"the break is longer than {decision.force_fresh_after_days} days"
        )
        decision.reason = decision.reason or f"Starts fresh automatically: {why}."
    if decision.mode == RejoinMode.CONTINUE and decision._continue_blocked():
        if gratuity:
            decision.blocked.append(
                "Gratuity was paid when they left, so earlier service doesn't continue. "
                "Choose Start fresh."
            )
        else:
            decision.blocked.append(
                f"The break is longer than {decision.force_fresh_after_days} days. To continue "
                "anyway, record that the break is condoned and give a reason."
            )
    if decision.mode == RejoinMode.FRESH and not decision.reason:
        decision.blocked.append("Give a reason for starting fresh.")
    # What happens to the leave.
    balances = await _balances(session, tenant_id, emp, rejoin_on)
    for effect in balances:
        if decision.mode == RejoinMode.FRESH:
            effect.outcome = "LAPSE"
        else:
            effect.outcome = "KEPT"
    decision.leave = balances
    if decision.mode == RejoinMode.CONTINUE:
        decision.notes.append("Earlier service and any leave still held carry on.")
    else:
        decision.notes.append(
            "Earlier service stops counting for leave eligibility and any unused leave lapses."
        )
    decision.notes.append("Leave is not credited for the months they were away.")
    if strict and decision.blocked:
        raise HTTPException(422, " ".join(decision.blocked))
    return decision


async def apply_rejoin(
    session,
    tenant_id: UUID,
    emp: Employment,
    decision: RejoinDecision,
    *,
    personnel_action_id: UUID | None = None,
    actor: UUID | None = None,
) -> RejoinRecord:
    """Make the decision happen: settle the leave and open the next stint."""
    last = await _last_spell(session, tenant_id, emp)
    if last is not None and decision.gratuity_paid is not None:
        last.gratuity_paid = decision.gratuity_paid
        session.add(last)
    open_holds = list(
        (
            await session.execute(
                select(LeaveSeparationSettlement)
                .where(col(LeaveSeparationSettlement.tenant_id) == tenant_id)
                .where(col(LeaveSeparationSettlement.employment_id) == emp.id)
                .where(col(LeaveSeparationSettlement.action) == SeparationAction.HOLD)
                .where(col(LeaveSeparationSettlement.resolution).is_(None))
            )
        ).scalars()
    )
    summary: dict = {"kept": [], "lapsed": []}
    if decision.mode == RejoinMode.FRESH:
        fy = await resolve_employee_fy_start_month(session, tenant_id, emp.id)
        for effect in decision.leave:
            await record_transaction(
                session,
                tenant_id,
                employment_id=emp.id,
                bucket_id=effect.bucket_id,
                leave_type_id=effect.leave_type_id,
                transaction_type=LeaveTransactionType.LAPSE,
                quantity=effect.days,
                effective_date=decision.rejoin_on,
                reason="Rejoined and started fresh",
                reference_id=personnel_action_id,
                reference_type="REJOIN",
                recorded_by=actor or SYSTEM_ACTOR,
                fy_start_month=fy,
            )
            summary["lapsed"].append(
                {"leave_type_id": str(effect.leave_type_id), "days": effect.days}
            )
        for hold in open_holds:
            hold.resolution = SettlementResolution.LAPSED
            hold.resolved_on = decision.rejoin_on
            hold.lapsed_days = _half(hold.days - hold.encashed_days)
            session.add(hold)
    else:
        for hold in open_holds:
            hold.resolution = SettlementResolution.RESTORED
            hold.resolved_on = decision.rejoin_on
            session.add(hold)
        summary["kept"] = [
            {"leave_type_id": str(e.leave_type_id), "days": e.days} for e in decision.leave
        ]
    await session.flush()
    REJOINS.labels(decision.mode.value).inc()
    return await spells.open_next_spell(
        session,
        tenant_id,
        emp,
        decision.rejoin_on,
        mode=decision.mode,
        reason=decision.reason,
        break_start=decision.left_on,
        restored_leave=summary,
        personnel_action_id=personnel_action_id,
        actor=actor,
    )

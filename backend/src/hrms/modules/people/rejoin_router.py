"""
Rejoining (docs/REJOIN_DEVELOPMENT_PLAN.md, R3).

  GET    /v1/employees/{employment_id}/rejoin-preview   what rejoining on a date would do
  GET    /v1/people/rejoin-policies
  POST   /v1/people/rejoin-policies          (people.write)
  DELETE /v1/people/rejoin-policies/{id}     (people.write)  — archives the policy

The rejoin itself is a REHIRE personnel action (POST /v1/personnel-actions) carrying the choice.
"""

from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    ScopeDep,
    authorize_employment,
    require_global_permission,
    require_permission,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.people import rejoin
from hrms.modules.people.models import (
    Employment,
    EmploymentSpell,
    EmploymentState,
    RejoinPolicy,
    RejoinRecord,
)

router = APIRouter(tags=["People"])

Mode = Literal["CONTINUE", "FRESH"]


class LeaveEffectResponse(BaseModel):
    leave_type_id: str
    leave_type_name: str
    days: float
    outcome: Literal["KEPT", "LAPSE"]


class RejoinPreview(BaseModel):
    employment_id: str
    left_on: date | None
    rejoin_on: date
    gap_days: int | None
    mode: Mode
    default_mode: Mode
    allowed_modes: list[Mode]
    force_fresh_after_days: int | None
    gratuity_paid: bool | None
    automatic: bool
    reason: str | None
    can_proceed: bool
    blocked: list[str]
    notes: list[str]
    leave: list[LeaveEffectResponse]


class PersonEmployment(BaseModel):
    employment_id: str
    legal_entity_id: str
    employee_number: str
    employment_state: str
    hire_date: date
    separation_date: date | None
    can_rejoin: bool


class RejoinInfo(BaseModel):
    mode: Mode
    break_start: date | None
    break_end: date | None
    break_condoned: bool
    reason: str | None


class SpellResponse(BaseModel):
    spell_no: int
    joined_on: date
    left_on: date | None
    exit_reason: str | None
    gratuity_paid: bool | None
    rejoin: RejoinInfo | None


class EmploymentHistory(BaseModel):
    employment_id: str
    hire_date: date
    continuity_start_date: date | None
    spells: list[SpellResponse]


class RejoinPolicyCreate(BaseModel):
    legal_entity_id: str | None = Field(default=None, description="Blank = every company")
    default_mode: Mode
    force_fresh_after_days: int | None = Field(default=None, ge=0, le=36500)
    effective_from: date


class RejoinPolicyResponse(BaseModel):
    id: str
    legal_entity_id: str | None
    default_mode: Mode
    force_fresh_after_days: int | None
    effective_from: date


def _policy_resp(p: RejoinPolicy) -> RejoinPolicyResponse:
    return RejoinPolicyResponse(
        id=to_typed_id("rejoin_policy", p.id),
        legal_entity_id=to_typed_id("legal_entity", p.legal_entity_id)
        if p.legal_entity_id
        else None,
        default_mode=p.default_mode,
        force_fresh_after_days=p.force_fresh_after_days,
        effective_from=p.effective_from,
    )


@router.get(
    "/v1/employees/{employment_id}/rejoin-preview",
    response_model=RejoinPreview,
    dependencies=[require_permission("people.write")],
)
async def preview_rejoin(
    employment_id: str,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    effective_date: date | None = Query(default=None, description="Rejoin date; default today"),
    mode: Mode | None = Query(default=None, description="Check this choice instead of the default"),
    break_condoned: bool = Query(default=False),
    reason: str | None = Query(default=None, max_length=300),
    gratuity_paid_at_exit: bool | None = Query(default=None),
) -> RejoinPreview:
    scope = scope.for_permission("people.write")
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    emp = (
        (
            await session.execute(
                select(Employment)
                .where(col(Employment.tenant_id) == tenant_id)
                .where(col(Employment.id) == emp_uuid)
            )
        )
        .scalars()
        .first()
    )
    if emp is None:
        raise HTTPException(404, "Employment not found")
    if emp.employment_state != EmploymentState.SEPARATED:
        raise HTTPException(409, "Only someone who has left can rejoin")
    day = effective_date or business_today()
    choice = rejoin.RejoinChoice(
        mode=mode,
        break_condoned=break_condoned,
        reason=reason,
        gratuity_paid_at_exit=gratuity_paid_at_exit,
    )
    d = await rejoin.decide(session, tenant_id, emp, day, choice, strict=False)
    return RejoinPreview(
        employment_id=employment_id,
        left_on=d.left_on,
        rejoin_on=d.rejoin_on,
        gap_days=d.gap_days,
        mode=d.mode.value,
        default_mode=d.default_mode.value,
        allowed_modes=d.allowed_modes,
        force_fresh_after_days=d.force_fresh_after_days,
        gratuity_paid=d.gratuity_paid,
        automatic=d.automatic,
        reason=d.reason,
        can_proceed=not d.blocked,
        blocked=d.blocked,
        notes=d.notes,
        leave=[
            LeaveEffectResponse(
                leave_type_id=to_typed_id("leave_type", e.leave_type_id),
                leave_type_name=e.leave_type_name,
                days=e.days,
                outcome=e.outcome,
            )
            for e in d.leave
        ],
    )


@router.get(
    "/v1/employees/{employment_id}/employment-history",
    response_model=EmploymentHistory,
    dependencies=[require_permission("people.write")],
)
async def employment_history(
    employment_id: str, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
) -> EmploymentHistory:
    """Each stint of this employment, newest first, with how each rejoin was decided."""
    scope = scope.for_permission("people.write")
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    emp = (
        (
            await session.execute(
                select(Employment)
                .where(col(Employment.tenant_id) == tenant_id)
                .where(col(Employment.id) == emp_uuid)
            )
        )
        .scalars()
        .first()
    )
    if emp is None:
        raise HTTPException(404, "Employment not found")
    spells = (
        await session.execute(
            select(EmploymentSpell)
            .where(col(EmploymentSpell.tenant_id) == tenant_id)
            .where(col(EmploymentSpell.employment_id) == emp_uuid)
            .order_by(col(EmploymentSpell.spell_no).desc())
        )
    ).scalars()
    records = {
        r.new_spell_id: r
        for r in (
            await session.execute(
                select(RejoinRecord)
                .where(col(RejoinRecord.tenant_id) == tenant_id)
                .where(col(RejoinRecord.employment_id) == emp_uuid)
            )
        ).scalars()
    }
    return EmploymentHistory(
        employment_id=employment_id,
        hire_date=emp.hire_date,
        continuity_start_date=emp.continuity_start_date,
        spells=[
            SpellResponse(
                spell_no=sp.spell_no,
                joined_on=sp.joined_on,
                left_on=sp.left_on,
                exit_reason=sp.exit_reason,
                gratuity_paid=sp.gratuity_paid,
                rejoin=RejoinInfo(
                    mode=records[sp.id].mode,
                    break_start=records[sp.id].break_start,
                    break_end=records[sp.id].break_end,
                    break_condoned=records[sp.id].break_condoned,
                    reason=records[sp.id].reason,
                )
                if sp.id in records
                else None,
            )
            for sp in spells
        ],
    )


@router.get(
    "/v1/persons/{person_id}/employments",
    response_model=list[PersonEmployment],
    dependencies=[require_permission("people.write")],
)
async def list_person_employments(
    person_id: str, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
) -> list[PersonEmployment]:
    """Earlier and current employments of a person, so a hire can offer a rejoin instead."""
    scope = scope.for_permission("people.write")
    rows = (
        await session.execute(
            select(Employment)
            .where(col(Employment.tenant_id) == tenant_id)
            .where(col(Employment.person_id) == to_uuid(person_id))
            .where(col(Employment.archived_at).is_(None))
            .order_by(col(Employment.hire_date).desc())
        )
    ).scalars()
    return [
        PersonEmployment(
            employment_id=to_typed_id("employment", e.id),
            legal_entity_id=to_typed_id("legal_entity", e.legal_entity_id),
            employee_number=e.employee_number,
            employment_state=str(e.employment_state),
            hire_date=e.hire_date,
            separation_date=e.separation_date,
            can_rejoin=e.employment_state == EmploymentState.SEPARATED,
        )
        for e in rows
        if scope.covers_entity(e.legal_entity_id)
    ]


@router.get(
    "/v1/people/rejoin-policies",
    response_model=list[RejoinPolicyResponse],
    dependencies=[require_global_permission("people.read")],
)
async def list_rejoin_policies(
    tenant_id: TenantDep, session: SessionDep
) -> list[RejoinPolicyResponse]:
    rows = await session.execute(
        select(RejoinPolicy)
        .where(col(RejoinPolicy.tenant_id) == tenant_id)
        .where(col(RejoinPolicy.archived_at).is_(None))
        .order_by(col(RejoinPolicy.effective_from).desc())
    )
    return [_policy_resp(p) for p in rows.scalars()]


@router.post(
    "/v1/people/rejoin-policies",
    response_model=RejoinPolicyResponse,
    status_code=201,
    dependencies=[require_global_permission("people.write")],
)
async def create_rejoin_policy(
    body: RejoinPolicyCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> RejoinPolicyResponse:
    entity_id = to_uuid(body.legal_entity_id) if body.legal_entity_id else None
    if entity_id is not None:
        company = (
            await session.execute(
                text("SELECT 1 FROM legal_entities WHERE tenant_id = :t AND id = :i"),
                {"t": tenant_id, "i": entity_id},
            )
        ).first()
        if company is None:
            raise HTTPException(422, "That company doesn't exist")
    clash = (
        await session.execute(
            select(RejoinPolicy.id)
            .where(col(RejoinPolicy.tenant_id) == tenant_id)
            .where(col(RejoinPolicy.archived_at).is_(None))
            .where(col(RejoinPolicy.effective_from) == body.effective_from)
            .where(
                col(RejoinPolicy.legal_entity_id).is_(None)
                if entity_id is None
                else col(RejoinPolicy.legal_entity_id) == entity_id
            )
        )
    ).first()
    if clash is not None:
        raise HTTPException(409, "A rejoin policy for that company already starts on that date")
    policy = RejoinPolicy(
        tenant_id=tenant_id,
        id=uuid4(),
        legal_entity_id=entity_id,
        default_mode=body.default_mode,
        force_fresh_after_days=body.force_fresh_after_days,
        effective_from=body.effective_from,
        created_by=principal.user_account_id,
    )
    session.add(policy)
    await session.flush()
    return _policy_resp(policy)


@router.delete(
    "/v1/people/rejoin-policies/{policy_id}",
    status_code=204,
    dependencies=[require_global_permission("people.write")],
)
async def archive_rejoin_policy(policy_id: str, tenant_id: TenantDep, session: SessionDep):
    policy = (
        (
            await session.execute(
                select(RejoinPolicy)
                .where(col(RejoinPolicy.tenant_id) == tenant_id)
                .where(col(RejoinPolicy.id) == to_uuid(policy_id))
                .where(col(RejoinPolicy.archived_at).is_(None))
            )
        )
        .scalars()
        .first()
    )
    if policy is None:
        raise HTTPException(404, "No such policy")
    policy.archived_at = now_utc()
    session.add(policy)
    await session.flush()

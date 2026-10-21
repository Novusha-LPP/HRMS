"""
What happens to unused leave when someone leaves (docs/REJOIN_DEVELOPMENT_PLAN.md, R2).

  GET    /v1/leave/separation-rules                    rules in force and upcoming
  POST   /v1/leave/separation-rules          (leave.write)
  DELETE /v1/leave/separation-rules/{id}     (leave.write)  — archives the rule
  GET    /v1/leave/separation-preview        ?employment_id=&as_of=
  GET    /v1/leave/separation-settlements    ?employment_id=

Rules are company settings; the settlement itself runs when a SEPARATION personnel action is
applied (leave/separation.py), so there is no endpoint that settles by hand.
"""

from datetime import date
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
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
from hrms.modules.leave.models import (
    LeaveSeparationRule,
    LeaveSeparationSettlement,
    LeaveType,
)
from hrms.modules.leave.separation import plan_settlement
from hrms.modules.people.models import Employment

router = APIRouter(prefix="/v1/leave", tags=["Leave Management"])

Action = Literal["LAPSE", "ENCASH", "HOLD"]


class SeparationRuleCreate(BaseModel):
    legal_entity_id: str | None = Field(default=None, description="Blank = every company")
    leave_type_id: str | None = Field(default=None, description="Blank = every leave type")
    on_separation: Action
    hold_days: int | None = Field(default=None, ge=0, le=3650)
    max_encash_days: float | None = Field(default=None, ge=0, le=1000)
    effective_from: date

    @model_validator(mode="after")
    def _check(self):
        if self.hold_days is not None and self.on_separation != "HOLD":
            raise ValueError("hold_days only applies when on_separation is HOLD")
        if self.max_encash_days is not None:
            if self.on_separation != "ENCASH":
                raise ValueError("max_encash_days only applies when on_separation is ENCASH")
            if self.max_encash_days * 2 != int(self.max_encash_days * 2):
                raise ValueError("max_encash_days must be a whole or half number of days")
        return self


class SeparationRuleResponse(BaseModel):
    id: str
    legal_entity_id: str | None
    leave_type_id: str | None
    on_separation: Action
    hold_days: int | None
    max_encash_days: float | None
    effective_from: date


class PlannedSettlement(BaseModel):
    leave_type_id: str
    leave_type_name: str
    unused_days: float
    action: Action
    encash_days: float
    lapse_days: float
    held_days: float
    hold_expires_on: date | None
    note: str | None


class SettlementPreview(BaseModel):
    employment_id: str
    as_of: date
    items: list[PlannedSettlement]


class SeparationSettlementResponse(BaseModel):
    id: str
    employment_id: str
    leave_type_id: str
    days: float
    encashed_days: float
    lapsed_days: float
    action: Action
    settled_on: date
    hold_expires_on: date | None
    resolution: Literal["LAPSED", "RESTORED"] | None
    resolved_on: date | None


def _rule_resp(r: LeaveSeparationRule) -> SeparationRuleResponse:
    return SeparationRuleResponse(
        id=to_typed_id("leave_separation_rule", r.id),
        legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id)
        if r.legal_entity_id
        else None,
        leave_type_id=to_typed_id("leave_type", r.leave_type_id) if r.leave_type_id else None,
        on_separation=r.on_separation,
        hold_days=r.hold_days,
        max_encash_days=float(r.max_encash_days) if r.max_encash_days is not None else None,
        effective_from=r.effective_from,
    )


@router.get(
    "/separation-rules",
    response_model=list[SeparationRuleResponse],
    dependencies=[require_global_permission("leave.read")],
)
async def list_separation_rules(
    tenant_id: TenantDep, session: SessionDep
) -> list[SeparationRuleResponse]:
    rows = await session.execute(
        select(LeaveSeparationRule)
        .where(col(LeaveSeparationRule.tenant_id) == tenant_id)
        .where(col(LeaveSeparationRule.archived_at).is_(None))
        .order_by(col(LeaveSeparationRule.effective_from).desc())
    )
    return [_rule_resp(r) for r in rows.scalars()]


@router.post(
    "/separation-rules",
    response_model=SeparationRuleResponse,
    status_code=201,
    dependencies=[require_global_permission("leave.write")],
)
async def create_separation_rule(
    body: SeparationRuleCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> SeparationRuleResponse:
    entity_id = to_uuid(body.legal_entity_id) if body.legal_entity_id else None
    type_id = to_uuid(body.leave_type_id) if body.leave_type_id else None
    if entity_id is not None:
        company = (
            await session.execute(
                text("SELECT 1 FROM legal_entities WHERE tenant_id = :t AND id = :i"),
                {"t": tenant_id, "i": entity_id},
            )
        ).first()
        if company is None:
            raise HTTPException(422, "That company doesn't exist")
    if type_id is not None:
        leave_type = (
            (
                await session.execute(
                    select(LeaveType)
                    .where(col(LeaveType.tenant_id) == tenant_id)
                    .where(col(LeaveType.id) == type_id)
                    .where(col(LeaveType.archived_at).is_(None))
                )
            )
            .scalars()
            .first()
        )
        if leave_type is None:
            raise HTTPException(422, "That leave type doesn't exist")
        if body.on_separation == "ENCASH" and not leave_type.encashable:
            raise HTTPException(400, f"{leave_type.name} is not marked encashable")
    clash = (
        await session.execute(
            select(LeaveSeparationRule.id)
            .where(col(LeaveSeparationRule.tenant_id) == tenant_id)
            .where(col(LeaveSeparationRule.archived_at).is_(None))
            .where(col(LeaveSeparationRule.effective_from) == body.effective_from)
            .where(
                col(LeaveSeparationRule.legal_entity_id).is_(None)
                if entity_id is None
                else col(LeaveSeparationRule.legal_entity_id) == entity_id
            )
            .where(
                col(LeaveSeparationRule.leave_type_id).is_(None)
                if type_id is None
                else col(LeaveSeparationRule.leave_type_id) == type_id
            )
        )
    ).first()
    if clash is not None:
        raise HTTPException(
            409, "A rule for that company and leave type already starts on that date"
        )
    rule = LeaveSeparationRule(
        tenant_id=tenant_id,
        id=uuid4(),
        legal_entity_id=entity_id,
        leave_type_id=type_id,
        on_separation=body.on_separation,
        hold_days=body.hold_days,
        max_encash_days=body.max_encash_days,
        effective_from=body.effective_from,
        created_by=principal.user_account_id,
    )
    session.add(rule)
    await session.flush()
    return _rule_resp(rule)


@router.delete(
    "/separation-rules/{rule_id}",
    status_code=204,
    dependencies=[require_global_permission("leave.write")],
)
async def archive_separation_rule(rule_id: str, tenant_id: TenantDep, session: SessionDep):
    rule = (
        (
            await session.execute(
                select(LeaveSeparationRule)
                .where(col(LeaveSeparationRule.tenant_id) == tenant_id)
                .where(col(LeaveSeparationRule.id) == to_uuid(rule_id))
                .where(col(LeaveSeparationRule.archived_at).is_(None))
            )
        )
        .scalars()
        .first()
    )
    if rule is None:
        raise HTTPException(404, "No such rule")
    rule.archived_at = now_utc()
    session.add(rule)
    await session.flush()


async def _employment(session, tenant_id: UUID, employment_id: UUID) -> Employment:
    emp = (
        (
            await session.execute(
                select(Employment)
                .where(col(Employment.tenant_id) == tenant_id)
                .where(col(Employment.id) == employment_id)
            )
        )
        .scalars()
        .first()
    )
    if emp is None:
        raise HTTPException(404, "No such employee")
    return emp


@router.get(
    "/separation-preview",
    response_model=SettlementPreview,
    dependencies=[require_permission("leave.read")],
)
async def preview_separation_settlement(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str = Query(description="The employee who would leave"),
    as_of: date | None = Query(default=None, description="Last day; defaults to today"),
) -> SettlementPreview:
    scope = scope.for_permission("leave.read")
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    emp = await _employment(session, tenant_id, emp_uuid)
    day = as_of or business_today()
    plan = await plan_settlement(session, tenant_id, emp, day)
    return SettlementPreview(
        employment_id=employment_id,
        as_of=day,
        items=[
            PlannedSettlement(
                leave_type_id=to_typed_id("leave_type", i.leave_type_id),
                leave_type_name=i.leave_type_name,
                unused_days=i.days,
                action=i.action,
                encash_days=i.encash_days,
                lapse_days=i.lapse_days,
                held_days=i.held_days,
                hold_expires_on=i.hold_expires_on,
                note=i.note,
            )
            for i in plan
        ],
    )


@router.get(
    "/separation-settlements",
    response_model=list[SeparationSettlementResponse],
    dependencies=[require_permission("leave.read")],
)
async def list_separation_settlements(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str = Query(description="The employee"),
) -> list[SeparationSettlementResponse]:
    scope = scope.for_permission("leave.read")
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    rows = await session.execute(
        select(LeaveSeparationSettlement)
        .where(col(LeaveSeparationSettlement.tenant_id) == tenant_id)
        .where(col(LeaveSeparationSettlement.employment_id) == emp_uuid)
        .order_by(col(LeaveSeparationSettlement.settled_on).desc())
    )
    return [
        SeparationSettlementResponse(
            id=to_typed_id("leave_separation_settlement", s.id),
            employment_id=employment_id,
            leave_type_id=to_typed_id("leave_type", s.leave_type_id),
            days=s.days,
            encashed_days=s.encashed_days,
            lapsed_days=s.lapsed_days,
            action=s.action,
            settled_on=s.settled_on,
            hold_expires_on=s.hold_expires_on,
            resolution=s.resolution,
            resolved_on=s.resolved_on,
        )
        for s in rows.scalars()
    ]

"""
Moving a person to another company of the group (docs/REJOIN_DEVELOPMENT_PLAN.md, R7).

  GET  /v1/people/transfer-preview   what moving them would do
  POST /v1/people/transfers          (people.write over both companies)
"""

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, require_permission
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.modules.integrations.ownership import assert_lifecycle_allowed
from hrms.modules.people import transfer
from hrms.modules.people.models import Employment, TransferLeaveMode

router = APIRouter(tags=["People"])

LeaveMode = Literal["CARRY", "SETTLE"]


class TransferPlacement(BaseModel):
    org_unit_id: str
    location_id: str
    job_id: str
    grade_id: str | None = None
    position_id: str | None = None
    cost_centre_id: str | None = None
    manager_employment_id: str | None = None


class TransferRequest(BaseModel):
    employment_id: str
    legal_entity_id: str = Field(description="The company they are moving to")
    effective_date: date
    leave_mode: LeaveMode = "CARRY"
    placement: TransferPlacement
    employee_number: str | None = Field(default=None, max_length=50)
    reason: str | None = Field(default=None, max_length=300)


class LeaveLine(BaseModel):
    leave_type_id: str
    leave_type_name: str
    days: float


class TransferPreview(BaseModel):
    from_company: str
    to_company: str
    leave_mode: LeaveMode
    leave: list[LeaveLine]
    warnings: list[str]
    blocked: list[str]
    can_proceed: bool


class TransferResponse(BaseModel):
    from_employment_id: str
    to_employment_id: str
    employee_number: str
    leave_mode: LeaveMode


async def _load(session, tenant_id, employment_id) -> Employment:
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
        raise HTTPException(404, "Employment not found")
    return emp


@router.get(
    "/v1/people/transfer-preview",
    response_model=TransferPreview,
    dependencies=[require_permission("people.write")],
)
async def preview_company_transfer(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str = Query(description="Who would move"),
    legal_entity_id: str = Query(description="The company they would move to"),
    effective_date: date | None = Query(default=None),
    leave_mode: LeaveMode = Query(default="CARRY"),
) -> TransferPreview:
    scope = scope.for_permission("people.write")
    emp_uuid = to_uuid(employment_id)
    to_entity = to_uuid(legal_entity_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    emp = await _load(session, tenant_id, emp_uuid)
    today = business_today()
    plan = await transfer.plan_transfer(
        session, tenant_id, emp, to_entity, effective_date or today, today
    )
    if not scope.covers_entity(to_entity):
        plan.blocked.append("You can't manage the company they would move to.")
    carried = leave_mode == "CARRY"
    return TransferPreview(
        from_company=plan.from_company,
        to_company=plan.to_company,
        leave_mode=leave_mode,
        leave=[
            LeaveLine(
                leave_type_id=to_typed_id("leave_type", e.leave_type_id),
                leave_type_name=e.leave_type_name,
                days=e.days,
            )
            for e in plan.leave
        ]
        if carried
        else [],
        warnings=plan.warnings
        + ([] if carried else ["Unused leave follows this company's rules for leavers."]),
        blocked=plan.blocked,
        can_proceed=not plan.blocked,
    )


@router.post(
    "/v1/people/transfers",
    response_model=TransferResponse,
    status_code=201,
    dependencies=[require_permission("people.write")],
)
async def transfer_to_company(
    body: TransferRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> TransferResponse:
    from hrms.modules.people.router import _validate_assignment_references

    scope = scope.for_permission("people.write")
    emp_uuid = to_uuid(body.employment_id)
    to_entity = to_uuid(body.legal_entity_id)
    await lock_resource(session, tenant_id, f"personnel:{emp_uuid}")
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    if not scope.covers_entity(to_entity):
        raise HTTPException(403, "Not authorized to hire into that company")
    emp = await _load(session, tenant_id, emp_uuid)
    await assert_lifecycle_allowed(session, tenant_id, "exit", employment_id=emp.id)
    await assert_lifecycle_allowed(session, tenant_id, "hire", legal_entity_id=to_entity)
    today = business_today()
    plan = await transfer.plan_transfer(
        session, tenant_id, emp, to_entity, body.effective_date, today
    )
    if plan.blocked:
        raise HTTPException(422, " ".join(plan.blocked))
    placement: dict[str, Any] = {k: v for k, v in body.placement.model_dump().items() if v}
    # The placement is checked against the company they are moving to.
    probe = Employment(
        tenant_id=tenant_id,
        id=emp.id,
        person_id=emp.person_id,
        legal_entity_id=to_entity,
        employee_number=emp.employee_number,
        hire_date=emp.hire_date,
    )
    await _validate_assignment_references(session, tenant_id, probe, placement, scope)
    new, _ = await transfer.execute_transfer(
        session,
        tenant_id,
        emp,
        to_entity_id=to_entity,
        effective_date=body.effective_date,
        leave_mode=TransferLeaveMode(body.leave_mode),
        placement=placement,
        employee_number=body.employee_number,
        reason=(body.reason or "").strip() or None,
        actor_user=principal.user_account_id,
    )
    return TransferResponse(
        from_employment_id=to_typed_id("employment", emp.id),
        to_employment_id=to_typed_id("employment", new.id),
        employee_number=new.employee_number,
        leave_mode=body.leave_mode,
    )

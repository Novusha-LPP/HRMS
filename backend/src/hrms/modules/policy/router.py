"""
Policy module router.

GET    /v1/policies/templates               — list templates
POST   /v1/policies/templates               — create template
GET    /v1/policies/templates/{id}          — get template
PATCH  /v1/policies/templates/{id}          — update template
DELETE /v1/policies/templates/{id}          — archive template

GET    /v1/policies/assignments             — list employee assignments
POST   /v1/policies/assignments             — assign policy to employee
DELETE /v1/policies/assignments/{id}        — remove assignment

GET    /v1/policies/employee/{employment_id}/effective  — resolved policy for today
"""

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from hrms.core.authz import (
    ScopeDep,
    authorize_employment,
    authorize_org_unit,
    require_global_permission,
    require_permission,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import compute_standard_minutes, now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.org.models import LegalEntity, OrgUnit
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.policy.models import EmployeePolicyAssignment, PolicyTemplate
from hrms.modules.policy.schemas import (
    EmployeePolicyAssignCreate,
    EmployeePolicyAssignResponse,
    PolicyTemplateCreate,
    PolicyTemplateResponse,
    PolicyTemplateUpdate,
)

router = APIRouter(prefix="/v1/policies", tags=["HR Policies"])


# ─── Template CRUD ────────────────────────────────────────────────────────────


@router.get("/templates", response_model=list[PolicyTemplateResponse])
async def list_templates(
    *,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[PolicyTemplateResponse]:
    rows = await session.execute(
        select(PolicyTemplate)
        .where(PolicyTemplate.tenant_id == tenant_id)
        .where(PolicyTemplate.archived_at == None)  # noqa: E711
        .order_by(PolicyTemplate.name)
    )
    return [_tpl_response(t) for t in rows.scalars()]


@router.post(
    "/templates",
    response_model=PolicyTemplateResponse,
    status_code=201,
    dependencies=[require_global_permission("policy.write")],
)
async def create_template(
    body: PolicyTemplateCreate,
    *,
    tenant_id: TenantDep,
    session: SessionDep,
) -> PolicyTemplateResponse:
    # If this template is default, clear any existing default
    if body.is_default:
        await _clear_default(session, tenant_id)

    uid = uuid4()
    tpl = PolicyTemplate(
        tenant_id=tenant_id,
        id=uid,
        recorded_at=now_utc(),
        **body.model_dump(),
    )
    session.add(tpl)
    await session.flush()
    return _tpl_response(tpl)


@router.get("/templates/{template_id}", response_model=PolicyTemplateResponse)
async def get_template(
    template_id: str,
    *,
    tenant_id: TenantDep,
    session: SessionDep,
) -> PolicyTemplateResponse:
    tpl = await _get_tpl(session, tenant_id, template_id)
    return _tpl_response(tpl)


@router.patch(
    "/templates/{template_id}",
    response_model=PolicyTemplateResponse,
    dependencies=[require_global_permission("policy.write")],
)
async def update_template(
    template_id: str,
    body: PolicyTemplateUpdate,
    *,
    tenant_id: TenantDep,
    session: SessionDep,
) -> PolicyTemplateResponse:
    tpl = await _get_tpl(session, tenant_id, template_id)
    if body.is_default is True:
        await _clear_default(session, tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(tpl, k, v)
    session.add(tpl)
    await session.flush()
    return _tpl_response(tpl)


@router.delete(
    "/templates/{template_id}",
    status_code=204,
    dependencies=[require_global_permission("policy.write")],
)
async def archive_template(
    template_id: str,
    *,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    tpl = await _get_tpl(session, tenant_id, template_id)
    tpl.archived_at = now_utc()
    session.add(tpl)


# ─── Employee policy assignments ──────────────────────────────────────────────


@router.get("/assignments", response_model=list[EmployeePolicyAssignResponse])
async def list_assignments(
    *,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    employment_id: str | None = Query(default=None),
    org_unit_id: str | None = Query(default=None),
    legal_entity_id: str | None = Query(default=None),
) -> list[EmployeePolicyAssignResponse]:
    q = (
        select(EmployeePolicyAssignment, PolicyTemplate.name, OrgUnit.name, LegalEntity.name)
        .join(
            PolicyTemplate,
            col(PolicyTemplate.id) == col(EmployeePolicyAssignment.policy_template_id),
        )
        .outerjoin(OrgUnit, col(OrgUnit.id) == col(EmployeePolicyAssignment.org_unit_id))
        .outerjoin(
            LegalEntity, col(LegalEntity.id) == col(EmployeePolicyAssignment.legal_entity_id)
        )
        .where(EmployeePolicyAssignment.tenant_id == tenant_id)
        .where(EmployeePolicyAssignment.archived_at == None)  # noqa: E711
    )
    if employment_id:
        emp_uuid = to_uuid(employment_id)
        await authorize_employment(session, tenant_id, scope, emp_uuid)
        q = q.where(EmployeePolicyAssignment.employment_id == emp_uuid)
    elif org_unit_id:
        ou_uuid = to_uuid(org_unit_id)
        await authorize_org_unit(session, tenant_id, scope, ou_uuid)
        q = q.where(EmployeePolicyAssignment.org_unit_id == ou_uuid)
    elif legal_entity_id:
        le_uuid = to_uuid(legal_entity_id)
        if not scope.covers_entity(le_uuid):
            raise HTTPException(status_code=403, detail="Not authorized for this company")
        q = q.where(EmployeePolicyAssignment.legal_entity_id == le_uuid)
    else:
        scope = scope.for_permission("policy.read")
    if not scope.is_all:
        from hrms.core.authz import visible_employment_ids

        emp_ids = await visible_employment_ids(session, tenant_id, scope)
        from sqlalchemy import or_

        q = q.where(
            or_(
                col(EmployeePolicyAssignment.employment_id).in_(emp_ids),
                col(EmployeePolicyAssignment.org_unit_id).in_(scope.org_unit_ids),
                col(EmployeePolicyAssignment.legal_entity_id).in_(scope.legal_entity_ids),
            )
        )
    rows = await session.execute(q)
    return [
        EmployeePolicyAssignResponse(
            id=to_typed_id("employee_policy", a.id),
            employment_id=to_typed_id("employment", a.employment_id) if a.employment_id else None,
            org_unit_id=to_typed_id("org_unit", a.org_unit_id) if a.org_unit_id else None,
            legal_entity_id=to_typed_id("legal_entity", a.legal_entity_id)
            if a.legal_entity_id
            else None,
            policy_template_id=to_typed_id("policy_template", a.policy_template_id),
            effective_from=a.effective_from,
            effective_to=a.effective_to,
            ot_qualifying_minutes_override=a.ot_qualifying_minutes_override,
            grace_late_minutes_override=a.grace_late_minutes_override,
            grace_early_departure_minutes_override=a.grace_early_departure_minutes_override,
            ot_enabled_override=a.ot_enabled_override,
            ot_rate_override=a.ot_rate_override,
            policy_template_name=tpl_name,
            org_unit_name=ou_name,
            legal_entity_name=le_name,
        )
        for a, tpl_name, ou_name, le_name in rows
    ]


@router.post(
    "/assignments",
    response_model=EmployeePolicyAssignResponse,
    status_code=201,
    dependencies=[require_permission("policy.write")],
)
async def assign_policy(
    body: EmployeePolicyAssignCreate,
    *,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> EmployeePolicyAssignResponse:
    scope = scope.for_permission("policy.write")
    tpl_uuid = to_uuid(body.policy_template_id)
    emp_uuid = to_uuid(body.employment_id) if body.employment_id else None
    ou_uuid = to_uuid(body.org_unit_id) if body.org_unit_id else None
    le_uuid = to_uuid(body.legal_entity_id) if body.legal_entity_id else None
    ou_name = None
    le_name = None
    if emp_uuid:
        await authorize_employment(session, tenant_id, scope, emp_uuid)
    elif ou_uuid:
        await authorize_org_unit(session, tenant_id, scope, ou_uuid)
        ou_row = await session.execute(
            select(OrgUnit).where(OrgUnit.tenant_id == tenant_id).where(OrgUnit.id == ou_uuid)
        )
        ou = ou_row.scalars().first()
        if not ou:
            raise HTTPException(404, "Department not found")
        ou_name = ou.name
    else:
        if not scope.covers_entity(le_uuid):
            raise HTTPException(status_code=403, detail="Not authorized for this company")
        le_row = await session.execute(
            select(LegalEntity)
            .where(LegalEntity.tenant_id == tenant_id)
            .where(LegalEntity.id == le_uuid)
        )
        le = le_row.scalars().first()
        if not le:
            raise HTTPException(404, "Company not found")
        le_name = le.name

    # Verify template exists
    tpl_row = await session.execute(
        select(PolicyTemplate)
        .where(PolicyTemplate.tenant_id == tenant_id)
        .where(PolicyTemplate.id == tpl_uuid)
        .where(PolicyTemplate.archived_at == None)  # noqa: E711
    )
    tpl = tpl_row.scalars().first()
    if not tpl:
        raise HTTPException(404, "Policy template not found")

    uid = uuid4()
    asgn = EmployeePolicyAssignment(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        org_unit_id=ou_uuid,
        legal_entity_id=le_uuid,
        policy_template_id=tpl_uuid,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        ot_qualifying_minutes_override=body.ot_qualifying_minutes_override,
        grace_late_minutes_override=body.grace_late_minutes_override,
        grace_early_departure_minutes_override=body.grace_early_departure_minutes_override,
        ot_enabled_override=body.ot_enabled_override,
        ot_rate_override=body.ot_rate_override,
        recorded_at=now_utc(),
    )
    session.add(asgn)
    await session.flush()
    return EmployeePolicyAssignResponse(
        id=to_typed_id("employee_policy", uid),
        employment_id=body.employment_id,
        org_unit_id=body.org_unit_id,
        legal_entity_id=body.legal_entity_id,
        policy_template_id=body.policy_template_id,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        ot_qualifying_minutes_override=body.ot_qualifying_minutes_override,
        grace_late_minutes_override=body.grace_late_minutes_override,
        grace_early_departure_minutes_override=body.grace_early_departure_minutes_override,
        ot_enabled_override=body.ot_enabled_override,
        ot_rate_override=body.ot_rate_override,
        policy_template_name=tpl.name,
        org_unit_name=ou_name,
        legal_entity_name=le_name,
    )


@router.delete(
    "/assignments/{assignment_id}",
    status_code=204,
    dependencies=[require_permission("policy.write")],
)
async def remove_assignment(
    assignment_id: str,
    scope: ScopeDep,
    *,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    uid = to_uuid(assignment_id)
    row = await session.execute(
        select(EmployeePolicyAssignment)
        .where(EmployeePolicyAssignment.tenant_id == tenant_id)
        .where(EmployeePolicyAssignment.id == uid)
    )
    asgn = row.scalars().first()
    if not asgn:
        raise HTTPException(404, "Assignment not found")
    scope = scope.for_permission("policy.write")
    if asgn.employment_id:
        await authorize_employment(session, tenant_id, scope, asgn.employment_id)
    elif asgn.org_unit_id:
        await authorize_org_unit(session, tenant_id, scope, asgn.org_unit_id)
    elif not scope.covers_entity(asgn.legal_entity_id):
        raise HTTPException(403, "Not authorized for this company")
    asgn.archived_at = now_utc()
    session.add(asgn)


@router.get("/employee/{employment_id}/effective")
async def get_effective_policy(
    employment_id: str,
    *,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    work_date: date = Query(default=None),
) -> dict:
    if work_date is None:
        from datetime import date as d_

        work_date = d_.today()
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    policy = await resolve_policy(emp_uuid, work_date, session, tenant_id)
    return {
        "employment_id": employment_id,
        "work_date": work_date.isoformat(),
        **policy.__dict__,
        "expected_start_time": policy.expected_start_time.isoformat(),
        "expected_end_time": policy.expected_end_time.isoformat(),
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _tpl_response(t: PolicyTemplate) -> PolicyTemplateResponse:
    std = compute_standard_minutes(t.expected_start_time, t.expected_end_time, t.break_minutes)
    return PolicyTemplateResponse(
        id=to_typed_id("policy_template", t.id),
        name=t.name,
        description=t.description,
        is_default=t.is_default,
        timezone=t.timezone,
        expected_start_time=t.expected_start_time,
        expected_end_time=t.expected_end_time,
        work_days=t.work_days,
        saturday_pattern=t.saturday_pattern,
        break_minutes=t.break_minutes,
        break_auto_deduct=t.break_auto_deduct,
        grace_late_minutes=t.grace_late_minutes,
        grace_early_departure_minutes=t.grace_early_departure_minutes,
        half_day_threshold_pct=t.half_day_threshold_pct,
        ot_enabled=t.ot_enabled,
        ot_qualifying_minutes=t.ot_qualifying_minutes,
        ot_rate=t.ot_rate,
        ot_daily_cap_minutes=t.ot_daily_cap_minutes,
        off_day_work=t.off_day_work,
        punch_rounding_minutes=t.punch_rounding_minutes,
        punch_rounding_direction=t.punch_rounding_direction,
        correction_requires_approval=t.correction_requires_approval,
        correction_approval_levels=t.correction_approval_levels,
        standard_minutes=std,
    )


async def _get_tpl(session, tenant_id, template_id: str) -> PolicyTemplate:
    uid = to_uuid(template_id)
    row = await session.execute(
        select(PolicyTemplate)
        .where(PolicyTemplate.tenant_id == tenant_id)
        .where(PolicyTemplate.id == uid)
    )
    tpl = row.scalars().first()
    if not tpl:
        raise HTTPException(404, "Policy template not found")
    return tpl


async def _clear_default(session, tenant_id) -> None:
    rows = await session.execute(
        select(PolicyTemplate)
        .where(PolicyTemplate.tenant_id == tenant_id)
        .where(PolicyTemplate.is_default == True)  # noqa: E712
    )
    for t in rows.scalars():
        t.is_default = False
        session.add(t)

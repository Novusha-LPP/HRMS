"""
People module — /v1/persons, /v1/employees, /v1/personnel-actions.

POST /v1/personnel-actions is the only write path for employment changes —
including placing someone in a department for the first time. Creating an
Employment record alone does NOT give them a department, job title,
location or manager; submitting a HIRE personnel action does (see
_apply_personnel_action below). A direct PATCH on an assignment is rejected
by design — every change is a new effective-dated slice, so the org chart
has full history.

list_employees / list_persons used to return every person in the tenant
regardless of who asked — an accountant scoped to two companies could read
every sister company's headcount. Both are now filtered to the caller's
scope. Creating a person or hiring them into a legal entity requires
people.write AND that entity being within the caller's scope, so a
company-scoped HR manager can't quietly hire someone into a company they
don't administer.
"""

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, require_permission
from hrms.core.database import SessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.kernel.models import UserAccount
from hrms.modules.people.models import (
    Assignment,
    AssignmentManager,
    Employment,
    EmploymentState,
    Person,
    PersonnelAction,
    PersonnelActionStatus,
    PersonnelActionType,
)
from hrms.modules.people.schemas import (
    EmploymentCreate,
    EmploymentResponse,
    MyProfileResponse,
    MyProfileUpdate,
    PersonCreate,
    PersonnelActionCreate,
    PersonnelActionListItem,
    PersonnelActionResponse,
    PersonResponse,
)

router = APIRouter(tags=["People"])

_ASSIGNMENT_ACTIONS = {
    PersonnelActionType.HIRE, PersonnelActionType.REHIRE, PersonnelActionType.TRANSFER,
    PersonnelActionType.PROMOTION, PersonnelActionType.DEMOTION,
    PersonnelActionType.CHANGE_MANAGER, PersonnelActionType.CHANGE_GRADE,
    PersonnelActionType.CHANGE_COST_CENTRE,
}
_INITIAL_PLACEMENT = {PersonnelActionType.HIRE, PersonnelActionType.REHIRE}

# The columns every employee list/detail response enriches with, joining the
# employee's CURRENT (open) assignment. One shared fragment so the two
# endpoints can't quietly drift apart.
_EMPLOYEE_SELECT = """
    SELECT
        e.id, e.person_id, e.legal_entity_id, e.employee_number, e.hire_date,
        e.separation_date, e.employment_state, e.service_stage, e.version,
        le.name AS legal_entity_name,
        a.org_unit_id, ou.name AS department,
        a.job_id, j.title AS designation,
        a.location_id, l.name AS location,
        am.manager_employment_id,
        mp.legal_first_name || ' ' || mp.legal_last_name AS manager_name
    FROM employments e
    JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id AND a.effective_to IS NULL
    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
    LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
    LEFT JOIN locations l ON l.tenant_id = a.tenant_id AND l.id = a.location_id
    LEFT JOIN assignment_managers am
        ON am.tenant_id = a.tenant_id AND am.assignment_id = a.id
       AND am.manager_type = 'LINE' AND am.effective_to IS NULL
    LEFT JOIN employments me ON me.tenant_id = e.tenant_id AND me.id = am.manager_employment_id
    LEFT JOIN persons mp ON mp.tenant_id = me.tenant_id AND mp.id = me.person_id
"""


def _employment_row_response(r) -> EmploymentResponse:
    return EmploymentResponse(
        id=to_typed_id("employment", r.id),
        person_id=to_typed_id("person", r.person_id),
        legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id),
        employee_number=r.employee_number,
        hire_date=r.hire_date,
        separation_date=r.separation_date,
        employment_state=r.employment_state,
        service_stage=r.service_stage,
        version=r.version,
        legal_entity_name=r.legal_entity_name,
        org_unit_id=to_typed_id("org_unit", r.org_unit_id) if r.org_unit_id else None,
        department=r.department,
        job_id=to_typed_id("job", r.job_id) if r.job_id else None,
        designation=r.designation,
        location_id=to_typed_id("location", r.location_id) if r.location_id else None,
        location=r.location,
        manager_employment_id=to_typed_id("employment", r.manager_employment_id) if r.manager_employment_id else None,
        manager_name=r.manager_name,
    )


# ─── Persons ─────────────────────────────────────────────────────────────────

@router.post(
    "/v1/persons",
    response_model=PersonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a person record",
    dependencies=[require_permission("people.write")],
)
async def create_person(
    body: PersonCreate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> PersonResponse:
    uid = uuid4()
    person = Person(
        tenant_id=tenant_id,
        id=uid,
        legal_first_name=body.legal_first_name,
        legal_last_name=body.legal_last_name,
        preferred_name=body.preferred_name,
        date_of_birth=body.date_of_birth,
        gender=body.gender,
        nationality=body.nationality,
    )
    session.add(person)
    await session.flush()
    return PersonResponse(
        id=to_typed_id("person", uid),
        legal_first_name=person.legal_first_name,
        legal_last_name=person.legal_last_name,
        preferred_name=person.preferred_name,
        date_of_birth=person.date_of_birth,
        gender=person.gender,
        version=person.version,
    )


@router.get(
    "/v1/persons",
    response_model=list[PersonResponse],
    summary="List persons visible to the caller",
)
async def list_persons(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    limit: int = Query(default=50, le=200),
) -> list[PersonResponse]:
    # Persons have no legal_entity_id of their own — visibility is derived
    # from having at least one employment the caller's scope covers.
    if scope.is_all:
        q = (
            select(Person)
            .where(Person.tenant_id == tenant_id)
            .where(Person.archived_at.is_(None))  # type: ignore[attr-defined]
            .limit(limit)
        )
        rows = await session.execute(q)
        persons = list(rows.scalars())
    else:
        clause, params = scope.employment_filter_sql("e")
        person_rows = await session.execute(
            text(f"""
                SELECT DISTINCT p.id FROM persons p
                JOIN employments e ON e.tenant_id = p.tenant_id AND e.person_id = p.id
                WHERE p.tenant_id = CAST(:tid AS uuid) AND p.archived_at IS NULL
                  {clause}
                LIMIT :limit
            """),
            {"tid": str(tenant_id), "limit": limit, **params},
        )
        ids = [r[0] for r in person_rows]
        if not ids:
            persons = []
        else:
            rows = await session.execute(select(Person).where(Person.id.in_(ids)))  # type: ignore[attr-defined]
            persons = list(rows.scalars())

    return [
        PersonResponse(
            id=to_typed_id("person", r.id),
            legal_first_name=r.legal_first_name,
            legal_last_name=r.legal_last_name,
            preferred_name=r.preferred_name,
            date_of_birth=r.date_of_birth,
            gender=r.gender,
            version=r.version,
        )
        for r in persons
    ]


# ─── Your own profile (/v1/persons/me) ───────────────────────────────────────
#
# Deliberately not permission-gated: like list_balances in leave/router.py
# and every other self-service endpoint, "it's literally your own record"
# is the authorization — resolve_acting_employment_id's underlying idea
# (principal.employment_id, never a client-supplied id) applies here too,
# just without the optional "act on someone else's behalf" branch those
# endpoints have, since a profile edit is never done for someone else.
# `self.read`/`self.write` in core/authz.py are NOT used to gate this: they're
# only granted to the EMPLOYEE role bundle, but every role has a person and
# should be able to see/edit their own basic details regardless of what
# admin permissions they separately hold.

@router.get("/v1/persons/me", response_model=MyProfileResponse, summary="Your own profile")
async def get_my_profile(principal: CurrentUser, tenant_id: TenantDep, session: SessionDep) -> MyProfileResponse:
    if not principal.employment_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account has no employment record")
    row = (
        await session.execute(
            text("""
                SELECT p.id, p.legal_first_name, p.legal_last_name, p.preferred_name,
                       p.date_of_birth, p.gender, p.nationality, p.version,
                       ua.email, ua.mobile
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
                WHERE e.tenant_id = :tid AND e.id = :eid
            """),
            {"tid": str(tenant_id), "eid": str(principal.employment_id)},
        )
    ).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return _my_profile_response(row)


@router.patch("/v1/persons/me", response_model=MyProfileResponse, summary="Update your own profile")
async def update_my_profile(
    body: MyProfileUpdate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep,
) -> MyProfileResponse:
    if not principal.employment_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account has no employment record")

    emp = (
        await session.execute(
            select(Employment).where(Employment.tenant_id == tenant_id).where(Employment.id == principal.employment_id)
        )
    ).scalars().first()
    if not emp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    person = (
        await session.execute(
            select(Person).where(Person.tenant_id == tenant_id).where(Person.id == emp.person_id)
        )
    ).scalars().first()
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")

    fields = body.model_dump(exclude_unset=True)
    if "mobile" in fields:
        account = (
            await session.execute(
                select(UserAccount).where(UserAccount.tenant_id == tenant_id).where(UserAccount.id == principal.user_account_id)
            )
        ).scalars().first()
        if account:
            account.mobile = fields.pop("mobile")
            session.add(account)
    for k, v in fields.items():
        setattr(person, k, v)
    session.add(person)
    await session.flush()

    row = (
        await session.execute(
            text("""
                SELECT p.id, p.legal_first_name, p.legal_last_name, p.preferred_name,
                       p.date_of_birth, p.gender, p.nationality, p.version,
                       ua.email, ua.mobile
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
                WHERE e.tenant_id = :tid AND e.id = :eid
            """),
            {"tid": str(tenant_id), "eid": str(principal.employment_id)},
        )
    ).mappings().first()
    return _my_profile_response(row)


def _my_profile_response(r) -> MyProfileResponse:
    return MyProfileResponse(
        id=to_typed_id("person", r["id"]),
        legal_first_name=r["legal_first_name"],
        legal_last_name=r["legal_last_name"],
        preferred_name=r["preferred_name"],
        date_of_birth=r["date_of_birth"],
        gender=r["gender"],
        nationality=r["nationality"],
        email=r["email"],
        mobile=r["mobile"],
        version=r["version"],
    )


# ─── Employments (/v1/employees) ─────────────────────────────────────────────

@router.post(
    "/v1/employees",
    response_model=EmploymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an employment (hire a person)",
    dependencies=[require_permission("people.write")],
)
async def create_employment(
    body: EmploymentCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> EmploymentResponse:
    le_uuid = to_uuid(body.legal_entity_id)
    if not scope.covers_entity(le_uuid):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to hire into this legal entity")

    uid = uuid4()
    person_uuid = to_uuid(body.person_id)

    emp = Employment(
        tenant_id=tenant_id,
        id=uid,
        person_id=person_uuid,
        legal_entity_id=le_uuid,
        employee_number=body.employee_number,
        hire_date=body.hire_date,
        service_stage=body.service_stage,
    )
    session.add(emp)
    await session.flush()
    # No assignment yet at this point — the caller still needs to submit a
    # HIRE personnel action to actually place them in a department. Name/
    # department/etc. are correctly null here.
    return EmploymentResponse(
        id=to_typed_id("employment", uid),
        person_id=body.person_id,
        legal_entity_id=body.legal_entity_id,
        employee_number=emp.employee_number,
        hire_date=emp.hire_date,
        separation_date=emp.separation_date,
        employment_state=emp.employment_state,
        service_stage=emp.service_stage,
        version=emp.version,
    )


@router.get(
    "/v1/employees",
    response_model=list[EmploymentResponse],
    summary="List employments visible to the caller, with their current department/job/location/manager",
)
async def list_employees(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    limit: int = Query(default=50, le=200),
    status_filter: EmploymentState | None = Query(default=None, alias="filter[status]"),
) -> list[EmploymentResponse]:
    where = ["e.tenant_id = CAST(:tid AS uuid)", "e.archived_at IS NULL"]
    params: dict = {"tid": str(tenant_id), "limit": limit}
    if status_filter:
        where.append("e.employment_state = :state")
        params["state"] = status_filter.value
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params.update(entity_params)

    rows = await session.execute(
        text(f"{_EMPLOYEE_SELECT} WHERE {' AND '.join(where)} {entity_clause} ORDER BY e.employee_number LIMIT :limit"),
        params,
    )
    return [_employment_row_response(r) for r in rows.mappings().all()]


@router.get(
    "/v1/employees/{employment_id}",
    response_model=EmploymentResponse,
    summary="Get one employee's current department/job/location/manager",
)
async def get_employee(
    employment_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> EmploymentResponse:
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    row = (await session.execute(
        text(f"{_EMPLOYEE_SELECT} WHERE e.tenant_id = CAST(:tid AS uuid) AND e.id = CAST(:eid AS uuid)"),
        {"tid": str(tenant_id), "eid": str(emp_uuid)},
    )).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return _employment_row_response(row)


# ─── Personnel Actions ───────────────────────────────────────────────────────

@router.post(
    "/v1/personnel-actions",
    response_model=PersonnelActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a personnel action (hire, transfer, promotion, separation, …) — applied immediately",
    dependencies=[require_permission("people.write")],
)
async def create_personnel_action(
    body: PersonnelActionCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> PersonnelActionResponse:
    emp_uuid = to_uuid(body.employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    if body.idempotency_key:
        existing = await session.execute(
            select(PersonnelAction)
            .where(PersonnelAction.tenant_id == tenant_id)
            .where(PersonnelAction.idempotency_key == body.idempotency_key)
        )
        if row := existing.scalars().first():
            return _pa_response(row)

    emp_row = await session.execute(
        select(Employment).where(Employment.tenant_id == tenant_id).where(Employment.id == emp_uuid)
    )
    emp = emp_row.scalars().first()
    if not emp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employment not found")

    uid = uuid4()
    pa = PersonnelAction(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        type=body.type,
        reason_code=body.reason_code,
        effective_date=body.effective_date,
        changes=body.changes,
        status=PersonnelActionStatus.PENDING_APPROVAL,
        idempotency_key=body.idempotency_key,
        submitted_at=datetime.now(timezone.utc),
    )
    session.add(pa)
    await session.flush()

    # Submitting this already required people.write scoped to this employee
    # (checked above) — that permission check IS the approval, so every
    # action type applies immediately rather than sitting in a
    # PENDING_APPROVAL state nothing can ever move out of.
    await _apply_personnel_action(session, tenant_id, pa, emp)
    pa.status = PersonnelActionStatus.APPLIED
    session.add(pa)
    await session.flush()

    return _pa_response(pa)


@router.get(
    "/v1/personnel-actions",
    response_model=list[PersonnelActionListItem],
    summary="List personnel actions for an employment",
)
async def list_personnel_actions(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    employment_id: str = Query(description="Typed employment ID (emp_...)"),
    limit: int = Query(default=50, le=200),
) -> list[PersonnelActionListItem]:
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    rows = await session.execute(
        select(PersonnelAction)
        .where(PersonnelAction.tenant_id == tenant_id)
        .where(PersonnelAction.employment_id == emp_uuid)
        .order_by(PersonnelAction.effective_date.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    return [
        PersonnelActionListItem(
            id=to_typed_id("personnel_action", r.id),
            type=r.type,
            effective_date=r.effective_date,
            status=r.status,
            submitted_at=r.submitted_at,
        )
        for r in rows.scalars()
    ]


# ─── Applying a personnel action to the org chart ─────────────────────────────

async def _current_assignment(session, tenant_id: UUID, employment_id: UUID) -> Assignment | None:
    row = await session.execute(
        select(Assignment)
        .where(Assignment.tenant_id == tenant_id)
        .where(Assignment.employment_id == employment_id)
        .where(Assignment.effective_to.is_(None))  # type: ignore[attr-defined]
    )
    return row.scalars().first()


async def _current_line_manager(session, tenant_id: UUID, assignment_id: UUID) -> UUID | None:
    row = await session.execute(
        select(AssignmentManager)
        .where(AssignmentManager.tenant_id == tenant_id)
        .where(AssignmentManager.assignment_id == assignment_id)
        .where(AssignmentManager.manager_type == "LINE")
        .where(AssignmentManager.effective_to.is_(None))  # type: ignore[attr-defined]
    )
    am = row.scalars().first()
    return am.manager_employment_id if am else None


def _changed_uuid(changes: dict, key: str) -> UUID | None:
    val = changes.get(key)
    if not val:
        return None
    try:
        return to_uuid(val) if isinstance(val, str) and "_" in val else UUID(str(val))
    except (ValueError, IndexError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid id for {key}: {val!r}")


async def _place_assignment(
    session, tenant_id: UUID, employment_id: UUID, effective_date: date,
    changes: dict, current: Assignment | None,
) -> Assignment:
    """
    Close the current assignment slice (if any) exactly where the new one
    starts and open a new one. Fields not present in `changes` carry forward
    from the current assignment — so e.g. a manager change doesn't require
    re-stating the department. org_unit/location/job are required overall
    (by the very first placement, or by carry-forward from then on).
    """
    org_unit_id = _changed_uuid(changes, "org_unit_id") or (current.org_unit_id if current else None)
    location_id = _changed_uuid(changes, "location_id") or (current.location_id if current else None)
    job_id = _changed_uuid(changes, "job_id") or (current.job_id if current else None)
    grade_id = _changed_uuid(changes, "grade_id") or (current.grade_id if current else None)
    position_id = _changed_uuid(changes, "position_id") or (current.position_id if current else None)
    cost_centre_id = _changed_uuid(changes, "cost_centre_id") or (current.cost_centre_id if current else None)

    if org_unit_id is None or location_id is None or job_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "changes must include org_unit_id, location_id and job_id "
            "(department, location and job title are required to place an employee)",
        )

    manager_id = _changed_uuid(changes, "manager_employment_id")
    if manager_id is None and current is not None:
        manager_id = await _current_line_manager(session, tenant_id, current.id)

    if current is not None:
        if effective_date < current.effective_from:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Effective date can't be before the current assignment started")
        current.effective_to = effective_date
        session.add(current)
        mgr_rows = await session.execute(
            select(AssignmentManager)
            .where(AssignmentManager.tenant_id == tenant_id)
            .where(AssignmentManager.assignment_id == current.id)
            .where(AssignmentManager.effective_to.is_(None))  # type: ignore[attr-defined]
        )
        for am in mgr_rows.scalars():
            am.effective_to = effective_date
            session.add(am)

    new_assignment = Assignment(
        tenant_id=tenant_id, id=uuid4(), employment_id=employment_id,
        effective_from=effective_date, org_unit_id=org_unit_id, location_id=location_id,
        job_id=job_id, grade_id=grade_id, position_id=position_id, cost_centre_id=cost_centre_id,
    )
    session.add(new_assignment)
    await session.flush()

    if manager_id:
        session.add(AssignmentManager(
            tenant_id=tenant_id, id=uuid4(), assignment_id=new_assignment.id,
            manager_employment_id=manager_id, manager_type="LINE", effective_from=effective_date,
        ))

    return new_assignment


async def _apply_personnel_action(session, tenant_id: UUID, pa: PersonnelAction, emp: Employment) -> None:
    changes = pa.changes or {}
    action_type = PersonnelActionType(pa.type)

    if action_type in _ASSIGNMENT_ACTIONS:
        current = await _current_assignment(session, tenant_id, pa.employment_id)
        if action_type in _INITIAL_PLACEMENT and current is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This employee already has an active assignment")
        if action_type not in _INITIAL_PLACEMENT and current is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No active assignment to change — hire them first")
        await _place_assignment(session, tenant_id, pa.employment_id, pa.effective_date, changes, current)

    if action_type == PersonnelActionType.REHIRE:
        emp.employment_state = EmploymentState.PROBATION
        emp.separation_date = None
    elif action_type == PersonnelActionType.CONFIRM:
        emp.employment_state = EmploymentState.ACTIVE
    elif action_type == PersonnelActionType.PLACE_ON_NOTICE:
        emp.employment_state = EmploymentState.NOTICE
    elif action_type == PersonnelActionType.SEPARATION:
        emp.employment_state = EmploymentState.SEPARATED
        emp.separation_date = pa.effective_date
        current = await _current_assignment(session, tenant_id, pa.employment_id)
        if current:
            current.effective_to = pa.effective_date
            session.add(current)

    session.add(emp)
    await session.flush()


def _pa_response(pa: PersonnelAction) -> PersonnelActionResponse:
    return PersonnelActionResponse(
        id=to_typed_id("personnel_action", pa.id),
        employment_id=to_typed_id("employment", pa.employment_id),
        type=pa.type,
        reason_code=pa.reason_code,
        effective_date=pa.effective_date,
        status=pa.status,
        changes=pa.changes,
        version=pa.version,
    )

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

import logging
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    Scope,
    ScopeDep,
    authorize_employment,
    read_scope,
    require_permission,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.metrics import SCHEDULED_ACTIONS
from hrms.core.tenancy import TenantDep
from hrms.core.versioning import require_version
from hrms.modules.integrations import hooks as integration_hooks
from hrms.modules.integrations.ownership import (
    ASSIGNMENT_FIELDS,
    assert_fields_editable,
    assert_lifecycle_allowed,
)
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
logger = logging.getLogger(__name__)


def can_see_personal_details(scope: Scope) -> bool:
    """
    Date of birth and gender are personal data. Managers and accountants hold
    people.read to see who works where, not to see this — only HR (people.write)
    and administrators do. Everyone can always see their own.
    """
    return scope.has("people.write")


_ASSIGNMENT_ACTIONS = {
    PersonnelActionType.HIRE,
    PersonnelActionType.REHIRE,
    PersonnelActionType.TRANSFER,
    PersonnelActionType.PROMOTION,
    PersonnelActionType.DEMOTION,
    PersonnelActionType.CHANGE_MANAGER,
    PersonnelActionType.CHANGE_GRADE,
    PersonnelActionType.CHANGE_COST_CENTRE,
    PersonnelActionType.CHANGE_JOB,
}
_INITIAL_PLACEMENT = {PersonnelActionType.HIRE, PersonnelActionType.REHIRE}

# The employment states each status-changing action can start from. Checked when the
# action is applied (at once, or on its date for a scheduled one, where a refusal parks
# it as FAILED), so a confirmation can't reactivate someone who has already left.
_ALLOWED_FROM: dict[PersonnelActionType, set[str]] = {
    PersonnelActionType.CONFIRM: {EmploymentState.PROBATION},
    PersonnelActionType.EXTEND_PROBATION: {EmploymentState.PROBATION},
    PersonnelActionType.PLACE_ON_NOTICE: {
        EmploymentState.ACTIVE,
        EmploymentState.PROBATION,
        EmploymentState.ON_HOLD,
    },
    PersonnelActionType.SEPARATION: {
        EmploymentState.ACTIVE,
        EmploymentState.PROBATION,
        EmploymentState.NOTICE,
        EmploymentState.ON_HOLD,
    },
    PersonnelActionType.REHIRE: {EmploymentState.SEPARATED},
}
_ACTION_LABEL = {
    PersonnelActionType.CONFIRM: "Confirmation",
    PersonnelActionType.EXTEND_PROBATION: "A probation extension",
    PersonnelActionType.PLACE_ON_NOTICE: "Placing on notice",
    PersonnelActionType.SEPARATION: "A separation",
    PersonnelActionType.REHIRE: "A rehire",
}
_STATE_LABEL = {
    EmploymentState.ACTIVE: "confirmed",
    EmploymentState.PROBATION: "on probation",
    EmploymentState.NOTICE: "on notice",
    EmploymentState.ON_HOLD: "on hold",
    EmploymentState.SEPARATED: "separated",
}

# The columns every employee list/detail response enriches with, joining the
# employee's CURRENT (open) assignment. One shared fragment so the two
# endpoints can't quietly drift apart.
_EMPLOYEE_SELECT = """
    SELECT
        e.id, e.person_id, e.legal_entity_id, e.employee_number, e.hire_date,
        e.separation_date, e.employment_state, e.service_stage, e.version,
        le.name AS legal_entity_name,
        p.date_of_birth, p.gender,
        p.legal_first_name AS first_name,
        p.legal_last_name AS last_name,
        COALESCE(NULLIF(p.preferred_name, ''), p.legal_first_name) || ' ' || p.legal_last_name
            AS full_name,
        ua.email AS email,
        r.name AS role,
        a.org_unit_id,
        CASE WHEN ou.type = 'TEAM' THEN parent_ou.name ELSE ou.name END AS department,
        CASE WHEN ou.type = 'TEAM' THEN ou.name ELSE NULL END AS team_name,
        a.job_id, j.title AS designation,
        a.grade_id, g.name AS grade,
        a.position_id, pos.title AS position_title,
        a.location_id, l.name AS location,
        am.manager_employment_id,
        mp.legal_first_name || ' ' || mp.legal_last_name AS manager_name
    FROM employments e
    JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
    LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
    LEFT JOIN LATERAL (
        SELECT r.name
        FROM role_assignments ra
        JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
        WHERE ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
        ORDER BY CASE r.name
            WHEN 'SUPER_ADMIN' THEN 1
            WHEN 'HR_MANAGER' THEN 2
            WHEN 'MANAGER' THEN 3
            WHEN 'ACCOUNTANT' THEN 4
            ELSE 5 END
        LIMIT 1
    ) r ON TRUE
    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id AND
    (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE) AND a.effective_from <=
    CURRENT_DATE
    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
    LEFT JOIN org_units parent_ou ON parent_ou.tenant_id = ou.tenant_id
        AND parent_ou.id = ou.parent_id
    LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
    LEFT JOIN grades g ON g.tenant_id = a.tenant_id AND g.id = a.grade_id
    LEFT JOIN positions pos ON pos.tenant_id = a.tenant_id AND pos.id = a.position_id
    LEFT JOIN locations l ON l.tenant_id = a.tenant_id AND l.id = a.location_id
    LEFT JOIN assignment_managers am
        ON am.tenant_id = a.tenant_id AND am.assignment_id = a.id
       AND am.manager_type = 'LINE' AND am.effective_to IS NULL
    LEFT JOIN employments me ON me.tenant_id = e.tenant_id AND me.id = am.manager_employment_id
    LEFT JOIN persons mp ON mp.tenant_id = me.tenant_id AND mp.id = me.person_id
"""


async def _generate_employee_number(session, tenant_id: UUID, legal_entity_id: UUID) -> str | None:
    """
    Resolve the hiring company's own employee ID scheme, falling back to
    the tenant-wide one, and atomically consume the next number from
    whichever is found. Returns None if no scheme exists at all — the
    caller must then require employee_number to be supplied manually.

    The increment is a single UPDATE ... RETURNING, not a SELECT then
    UPDATE, so two employees hired at the same instant still get distinct
    numbers — Postgres serializes the row-level UPDATE.
    """
    row = await session.execute(
        text("""
            SELECT id, prefix, separator, number_digits
            FROM employee_id_schemes
            WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
              AND legal_entity_id = CAST(:leid AS uuid)
            LIMIT 1
        """),
        {"tid": str(tenant_id), "leid": str(legal_entity_id)},
    )
    scheme = row.mappings().first()
    if scheme is None:
        row = await session.execute(
            text("""
                SELECT id, prefix, separator, number_digits
                FROM employee_id_schemes
                WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
                  AND legal_entity_id IS NULL
                LIMIT 1
            """),
            {"tid": str(tenant_id)},
        )
        scheme = row.mappings().first()
    if scheme is None:
        return None

    # A number can already be taken: typed in by hand, or sent by a connected app (plan D-8).
    # Skip it rather than issue a duplicate.
    for _ in range(1000):
        issued = (
            await session.execute(
                text("""
                    UPDATE employee_id_schemes SET next_number = next_number + 1
                    WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:sid AS uuid)
                    RETURNING next_number - 1
                """),
                {"tid": str(tenant_id), "sid": str(scheme["id"])},
            )
        ).scalar()
        number = str(issued).zfill(scheme["number_digits"])
        code = f"{scheme['prefix']}{scheme['separator']}{number}"
        taken = (
            await session.execute(
                text("""
                    SELECT 1 FROM employments
                    WHERE tenant_id = CAST(:tid AS uuid) AND legal_entity_id = CAST(:leid AS uuid)
                      AND lower(employee_number) = lower(:code)
                """),
                {"tid": str(tenant_id), "leid": str(legal_entity_id), "code": code},
            )
        ).first()
        if not taken:
            return code
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "The employee ID scheme's next 1,000 numbers are all in use; move its counter on",
    )


def _employment_row_response(r, *, show_personal: bool = True) -> EmploymentResponse:
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
        date_of_birth=r.date_of_birth if show_personal else None,
        gender=r.gender if show_personal else None,
        first_name=r.first_name,
        last_name=r.last_name,
        full_name=r.full_name,
        email=getattr(r, "email", None),
        role=getattr(r, "role", None),
        legal_entity_name=r.legal_entity_name,
        org_unit_id=to_typed_id("org_unit", r.org_unit_id) if r.org_unit_id else None,
        department=r.department,
        team_name=r.team_name,
        job_id=to_typed_id("job", r.job_id) if r.job_id else None,
        designation=r.designation,
        grade_id=to_typed_id("grade", r.grade_id) if r.grade_id else None,
        grade=r.grade,
        position_id=to_typed_id("position", r.position_id) if r.position_id else None,
        position_title=r.position_title,
        location_id=to_typed_id("location", r.location_id) if r.location_id else None,
        location=r.location,
        manager_employment_id=to_typed_id("employment", r.manager_employment_id)
        if r.manager_employment_id
        else None,
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
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PersonResponse]:
    show_all_personal = can_see_personal_details(scope)
    # Only grants that carry people.read (plus the caller's own record) widen
    # what can be listed — a login's other, unrelated grants must not.
    scope = read_scope(scope, "people.read")
    own_person_id = None
    if principal.employment_id:
        own_person_id = (
            await session.execute(
                text("""
                    SELECT person_id FROM employments
                    WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:eid AS uuid)
                """),
                {"tid": str(tenant_id), "eid": str(principal.employment_id)},
            )
        ).scalar()
    # Persons have no legal_entity_id of their own — visibility is derived
    # from having at least one employment the caller's scope covers.
    if scope.is_all:
        q = (
            select(Person)
            .where(Person.tenant_id == tenant_id)
            .where(col(Person.archived_at).is_(None))
            .order_by(col(Person.id))  # stable order so offset paging never skips or repeats a row
            .limit(limit)
            .offset(offset)
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
                ORDER BY p.id
                LIMIT :limit OFFSET :offset
            """),
            {"tid": str(tenant_id), "limit": limit, "offset": offset, **params},
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
            date_of_birth=r.date_of_birth if show_all_personal or r.id == own_person_id else None,
            gender=r.gender if show_all_personal or r.id == own_person_id else None,
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
async def get_my_profile(
    principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> MyProfileResponse:
    if not principal.employment_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account has no employment record")
    row = (
        (
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
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return _my_profile_response(row)


@router.patch("/v1/persons/me", response_model=MyProfileResponse, summary="Update your own profile")
async def update_my_profile(
    body: MyProfileUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> MyProfileResponse:
    if not principal.employment_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account has no employment record")

    emp = (
        (
            await session.execute(
                select(Employment)
                .where(Employment.tenant_id == tenant_id)
                .where(Employment.id == principal.employment_id)
            )
        )
        .scalars()
        .first()
    )
    if not emp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    person = (
        (
            await session.execute(
                select(Person)
                .where(Person.tenant_id == tenant_id)
                .where(Person.id == emp.person_id)
            )
        )
        .scalars()
        .first()
    )
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")

    await require_version(session, person, body.version)
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    # Only what actually changes: the profile form sends every field, edited or not.
    current_mobile = (
        await session.execute(
            text("SELECT mobile FROM user_accounts WHERE tenant_id = :tid AND id = :uid"),
            {"tid": tenant_id, "uid": principal.user_account_id},
        )
    ).scalar()
    changing = {
        k
        for k, v in fields.items()
        if (current_mobile if k == "mobile" else getattr(person, k, None)) != v
    }
    await assert_fields_editable(
        session,
        tenant_id,
        emp.id,
        changing,
        actor="SELF",
        changed_by=principal.user_account_id,
    )
    before = await integration_hooks.employee_changed.before(session, tenant_id, emp.id)
    if "mobile" in fields:
        account = (
            (
                await session.execute(
                    select(UserAccount)
                    .where(UserAccount.tenant_id == tenant_id)
                    .where(UserAccount.id == principal.user_account_id)
                )
            )
            .scalars()
            .first()
        )
        if account:
            account.mobile = fields.pop("mobile")
            session.add(account)
    for k, v in fields.items():
        setattr(person, k, v)
    session.add(person)
    await session.flush()
    await integration_hooks.employee_changed.after(session, tenant_id, emp.id, before)

    row = (
        (
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
        )
        .mappings()
        .first()
    )
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
    scope = scope.for_permission("people.write")
    le_uuid = to_uuid(body.legal_entity_id)
    if not scope.covers_entity(le_uuid):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Not authorized to hire into this legal entity"
        )
    await assert_lifecycle_allowed(session, tenant_id, "hire", legal_entity_id=le_uuid)

    employee_number = body.employee_number
    if not employee_number:
        employee_number = await _generate_employee_number(session, tenant_id, le_uuid)
        if employee_number is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No employee ID scheme is configured for this company — provide employee_number "
                "directly, or set one up first (POST /v1/org/employee-id-schemes)",
            )

    uid = uuid4()
    person_uuid = to_uuid(body.person_id)
    person = (
        (
            await session.execute(
                select(Person).where(Person.tenant_id == tenant_id).where(Person.id == person_uuid)
            )
        )
        .scalars()
        .first()
    )
    entity = (
        await session.execute(
            text(
                "SELECT id FROM legal_entities "
                "WHERE tenant_id = :tid AND id = :id AND archived_at IS NULL"
            ),
            {"tid": tenant_id, "id": le_uuid},
        )
    ).first()
    if person is None or entity is None:
        raise HTTPException(422, "Person and company must exist in this tenant")

    emp = Employment(
        tenant_id=tenant_id,
        id=uid,
        person_id=person_uuid,
        legal_entity_id=le_uuid,
        employee_number=employee_number,
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
    summary="List employees and their current organization assignments",
)
async def list_employees(
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: EmploymentState | None = Query(default=None, alias="filter[status]"),
) -> list[EmploymentResponse]:
    show_all_personal = can_see_personal_details(scope)
    # Only grants that carry people.read (plus the caller's own record) count —
    # see read_scope. An EMPLOYEE login has no people.read, so however wide its
    # role assignment's scope is, it lists nothing but itself.
    scope = read_scope(scope, "people.read")
    where = ["e.tenant_id = CAST(:tid AS uuid)", "e.archived_at IS NULL"]
    params: dict = {"tid": str(tenant_id), "limit": limit, "offset": offset}
    if status_filter:
        where.append("e.employment_state = :state")
        params["state"] = status_filter.value
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params.update(entity_params)

    rows = await session.execute(
        text(
            f"{_EMPLOYEE_SELECT} WHERE {' AND '.join(where)} {entity_clause} "
            "ORDER BY e.employee_number, e.id LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    return [
        _employment_row_response(
            r, show_personal=show_all_personal or r["id"] == principal.employment_id
        )
        for r in rows.mappings().all()
    ]


@router.get(
    "/v1/employees/{employment_id}",
    response_model=EmploymentResponse,
    summary="Get one employee's current department/job/location/manager",
)
async def get_employee(
    employment_id: str,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> EmploymentResponse:
    emp_uuid = to_uuid(employment_id)
    show_personal = can_see_personal_details(scope) or emp_uuid == principal.employment_id
    await authorize_employment(session, tenant_id, read_scope(scope, "people.read"), emp_uuid)

    row = (
        (
            await session.execute(
                text(
                    f"{_EMPLOYEE_SELECT} WHERE e.tenant_id = CAST(:tid AS uuid) "
                    "AND e.id = CAST(:eid AS uuid)"
                ),
                {"tid": str(tenant_id), "eid": str(emp_uuid)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return _employment_row_response(row, show_personal=show_personal)


# ─── Personnel Actions ───────────────────────────────────────────────────────


@router.post(
    "/v1/personnel-actions",
    response_model=PersonnelActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply a personnel action, or schedule it for its effective date",
    dependencies=[require_permission("people.write")],
)
async def create_personnel_action(
    body: PersonnelActionCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> PersonnelActionResponse:
    scope = scope.for_permission("people.write")
    emp_uuid = to_uuid(body.employment_id)
    await lock_resource(session, tenant_id, f"personnel:{emp_uuid}")
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    approval_apps = await _check_integration_rules(session, tenant_id, principal, body, emp_uuid)

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

    await _validate_assignment_references(session, tenant_id, emp, body.changes or {}, scope)
    await _reject_conflicting_schedule(session, tenant_id, emp_uuid, body.type, body.effective_date)
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
        submitted_at=datetime.now(UTC),
    )
    session.add(pa)
    await session.flush()

    if approval_apps:
        # It overrides a field a connected app owns, and the app's settings require approval:
        # it waits in the employee's FIELD_OVERRIDE approval flow (see decide_field_override).
        from hrms.modules.approvals import service as approval_flow

        instance = await approval_flow.start(
            session,
            tenant_id,
            FIELD_OVERRIDE,
            pa.id,
            emp_uuid,
            request_snapshot={
                "apps": approval_apps,
                "reason": (body.override_reason or "").strip(),
                "type": str(body.type),
                "effective_date": body.effective_date.isoformat(),
                "changes": body.changes or {},
            },
        )
        if instance is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Changing this needs approval ({', '.join(approval_apps)} owns it), but no "
                "field-override approval flow is assigned to this employee. Assign one in "
                "Approval flows.",
            )
        return _pa_response(pa)

    # Submitting this already required people.write scoped to this employee
    # (checked above) — that permission check IS the approval, so every
    # action type applies immediately rather than sitting in a
    # PENDING_APPROVAL state nothing can ever move out of.
    if pa.effective_date > business_today():
        pa.status = PersonnelActionStatus.SCHEDULED
    else:
        await _apply_personnel_action(session, tenant_id, pa, emp)
        pa.status = PersonnelActionStatus.APPLIED
        pa.applied_at = datetime.now(UTC)
    session.add(pa)
    await session.flush()
    if pa.status == PersonnelActionStatus.SCHEDULED:
        await integration_hooks.personnel_action_scheduled(session, tenant_id, pa, emp)

    return _pa_response(pa)


_LIFECYCLE_OPERATION: dict[PersonnelActionType, Literal["hire", "job_change", "exit", "rehire"]] = {
    PersonnelActionType.HIRE: "hire",
    PersonnelActionType.REHIRE: "rehire",
    PersonnelActionType.SEPARATION: "exit",
    PersonnelActionType.TRANSFER: "job_change",
    PersonnelActionType.PROMOTION: "job_change",
    PersonnelActionType.DEMOTION: "job_change",
    PersonnelActionType.CHANGE_MANAGER: "job_change",
    PersonnelActionType.CHANGE_JOB: "job_change",
}


FIELD_OVERRIDE = "FIELD_OVERRIDE"


async def decide_field_override(session, tenant_id, principal, action_id, action, comments):
    """
    A decision in the employee's FIELD_OVERRIDE approval flow (from the approvals inbox). The
    final approval applies the held personnel action (or schedules it); a rejection drops it.
    """
    from hrms.modules.approvals import service as approval_flow

    await lock_resource(session, tenant_id, f"personnel:{action_id}")
    pa = (
        (
            await session.execute(
                select(PersonnelAction)
                .where(PersonnelAction.tenant_id == tenant_id)
                .where(PersonnelAction.id == action_id)
                .with_for_update()
            )
        )
        .scalars()
        .first()
    )
    if pa is None or pa.status != PersonnelActionStatus.PENDING_APPROVAL:
        raise HTTPException(status.HTTP_409_CONFLICT, "This change isn't awaiting approval")
    final = await approval_flow.record_decision(
        session, tenant_id, FIELD_OVERRIDE, pa.id, principal, action, comments
    )
    if action == "REJECT":
        pa.status = PersonnelActionStatus.REJECTED
    elif final:
        emp = (
            (
                await session.execute(
                    select(Employment)
                    .where(Employment.tenant_id == tenant_id)
                    .where(Employment.id == pa.employment_id)
                )
            )
            .scalars()
            .one()
        )
        await _reject_conflicting_schedule(
            session, tenant_id, pa.employment_id, PersonnelActionType(pa.type), pa.effective_date
        )
        if pa.effective_date > business_today():
            pa.status = PersonnelActionStatus.SCHEDULED
        else:
            await _apply_personnel_action(session, tenant_id, pa, emp)
            pa.status = PersonnelActionStatus.APPLIED
            pa.applied_at = datetime.now(UTC)
    session.add(pa)
    await session.flush()


async def _check_integration_rules(session, tenant_id, principal, body, emp_uuid) -> list[str]:
    """A connected app's settings may reserve this change, or these fields, for the app."""
    operation = _LIFECYCLE_OPERATION.get(PersonnelActionType(body.type))
    if operation:
        await assert_lifecycle_allowed(session, tenant_id, operation, employment_id=emp_uuid)
    # Only what actually changes: a form that resends the current department isn't changing it.
    current = await _current_assignment(session, tenant_id, emp_uuid)
    now = {}
    if current is not None:
        now = {
            "org_unit_id": current.org_unit_id,
            "location_id": current.location_id,
            "job_id": current.job_id,
            "manager_employment_id": await _current_line_manager(session, tenant_id, current.id),
        }
    fields = {
        ASSIGNMENT_FIELDS[k]
        for k in (body.changes or {})
        if k in ASSIGNMENT_FIELDS
        and (body.changes or {}).get(k)
        and _changed_uuid(body.changes or {}, k) != now.get(k)
    }
    if body.type == PersonnelActionType.SEPARATION:
        fields.add("last_working_day")
    return await assert_fields_editable(
        session,
        tenant_id,
        emp_uuid,
        fields,
        actor="HR",
        changed_by=principal.user_account_id,
        override_reason=body.override_reason,
    )


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
    await authorize_employment(session, tenant_id, read_scope(scope, "people.read"), emp_uuid)

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
            failure_reason=r.failure_reason,
            reason_code=r.reason_code,
            changes=r.changes,
        )
        for r in rows.scalars()
    ]


@router.post(
    "/v1/personnel-actions/{action_id}/cancel",
    response_model=PersonnelActionResponse,
    summary="Cancel a scheduled (or failed) personnel action",
    dependencies=[require_permission("people.write")],
)
async def cancel_personnel_action(
    action_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> PersonnelActionResponse:
    """
    A future-dated action (a separation, a transfer, ...) applies by itself on
    its effective date, so there has to be a way to stop one that was entered
    wrongly. Only SCHEDULED and FAILED actions can be cancelled — an APPLIED one
    is history; correct it with a new action instead.
    """
    scope = scope.for_permission("people.write")
    pa = (
        (
            await session.execute(
                select(PersonnelAction)
                .where(PersonnelAction.tenant_id == tenant_id)
                .where(PersonnelAction.id == to_uuid(action_id))
            )
        )
        .scalars()
        .first()
    )
    if not pa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Personnel action not found")
    await authorize_employment(session, tenant_id, scope, pa.employment_id)
    await lock_resource(session, tenant_id, f"personnel:{pa.employment_id}")
    await session.refresh(pa)  # re-read under the lock: it may have just been applied
    if pa.status not in (
        PersonnelActionStatus.SCHEDULED,
        PersonnelActionStatus.FAILED,
        PersonnelActionStatus.PENDING_APPROVAL,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only scheduled, failed or pending actions can be cancelled (this one is {pa.status})",
        )
    if pa.status == PersonnelActionStatus.PENDING_APPROVAL:
        # A field override waiting for approval: withdraw its approval request too.
        from hrms.modules.approvals import service as approval_flow

        await approval_flow.finish(session, tenant_id, FIELD_OVERRIDE, pa.id, "CANCELLED")
    pa.status = PersonnelActionStatus.CANCELLED
    session.add(pa)
    await session.flush()
    return _pa_response(pa)


async def _reject_conflicting_schedule(
    session, tenant_id: UUID, employment_id: UUID, new_type: PersonnelActionType, new_date: date
) -> None:
    """
    Refuse an action that a still-scheduled one would make impossible to apply.
    Nothing is validated when a future-dated action is accepted, so without this
    a separation on the 10th plus a transfer on the 20th are both accepted and
    the transfer can only fail when its day arrives. (The applier also copes
    with that case — see apply_due_actions — this just stops it being entered.)
    """
    scheduled = (
        await session.execute(
            select(col(PersonnelAction.type), col(PersonnelAction.effective_date))
            .where(PersonnelAction.tenant_id == tenant_id)
            .where(PersonnelAction.employment_id == employment_id)
            .where(PersonnelAction.status == PersonnelActionStatus.SCHEDULED)
        )
    ).all()
    for other_type, other_date in scheduled:
        if (
            other_type == PersonnelActionType.SEPARATION
            and new_type != PersonnelActionType.REHIRE
            and new_date >= other_date
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A separation is already scheduled for {other_date}. Cancel it first, or use "
                "a date before it.",
            )
        if (
            new_type == PersonnelActionType.SEPARATION
            and other_type != PersonnelActionType.REHIRE
            and other_date >= new_date
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A {other_type} is scheduled for {other_date}, on or after this separation. "
                "Cancel or reschedule it first.",
            )


# ─── Applying a personnel action to the org chart ─────────────────────────────


async def _current_assignment(session, tenant_id: UUID, employment_id: UUID) -> Assignment | None:
    row = await session.execute(
        select(Assignment)
        .where(Assignment.tenant_id == tenant_id)
        .where(Assignment.employment_id == employment_id)
        .where(Assignment.effective_from <= business_today())
        .where(
            (col(Assignment.effective_to).is_(None))
            | (col(Assignment.effective_to) > business_today())
        )
    )
    return row.scalars().first()


async def _current_line_manager(session, tenant_id: UUID, assignment_id: UUID) -> UUID | None:
    row = await session.execute(
        select(AssignmentManager)
        .where(AssignmentManager.tenant_id == tenant_id)
        .where(AssignmentManager.assignment_id == assignment_id)
        .where(AssignmentManager.manager_type == "LINE")
        .where(AssignmentManager.effective_from <= business_today())
        .where(
            (col(AssignmentManager.effective_to).is_(None))
            | (col(AssignmentManager.effective_to) > business_today())
        )
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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid id for {key}: {val!r}") from None


async def _place_assignment(
    session,
    tenant_id: UUID,
    employment_id: UUID,
    effective_date: date,
    changes: dict,
    current: Assignment | None,
) -> Assignment:
    """
    Close the current assignment slice (if any) exactly where the new one
    starts and open a new one. Fields not present in `changes` carry forward
    from the current assignment — so e.g. a manager change doesn't require
    re-stating the department. org_unit/location/job are required overall
    (by the very first placement, or by carry-forward from then on).
    """
    org_unit_id = _changed_uuid(changes, "org_unit_id") or (
        current.org_unit_id if current else None
    )
    location_id = _changed_uuid(changes, "location_id") or (
        current.location_id if current else None
    )
    job_id = _changed_uuid(changes, "job_id") or (current.job_id if current else None)
    grade_id = _changed_uuid(changes, "grade_id") or (current.grade_id if current else None)
    position_id = _changed_uuid(changes, "position_id") or (
        current.position_id if current else None
    )
    cost_centre_id = _changed_uuid(changes, "cost_centre_id") or (
        current.cost_centre_id if current else None
    )

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
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Effective date can't be before the current assignment started",
            )
        current.effective_to = effective_date
        session.add(current)
        mgr_rows = await session.execute(
            select(AssignmentManager)
            .where(AssignmentManager.tenant_id == tenant_id)
            .where(AssignmentManager.assignment_id == current.id)
            .where(AssignmentManager.effective_from <= business_today())
            .where(
                (col(AssignmentManager.effective_to).is_(None))
                | (col(AssignmentManager.effective_to) > business_today())
            )
        )
        for am in mgr_rows.scalars():
            am.effective_to = effective_date
            session.add(am)

    new_assignment = Assignment(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=employment_id,
        effective_from=effective_date,
        org_unit_id=org_unit_id,
        location_id=location_id,
        job_id=job_id,
        grade_id=grade_id,
        position_id=position_id,
        cost_centre_id=cost_centre_id,
    )
    session.add(new_assignment)
    await session.flush()

    if manager_id:
        session.add(
            AssignmentManager(
                tenant_id=tenant_id,
                id=uuid4(),
                assignment_id=new_assignment.id,
                manager_employment_id=manager_id,
                manager_type="LINE",
                effective_from=effective_date,
            )
        )

    return new_assignment


async def _apply_personnel_action(
    session, tenant_id: UUID, pa: PersonnelAction, emp: Employment
) -> None:
    before = await integration_hooks.capture(session, tenant_id, pa.employment_id)
    await _apply_personnel_action_change(session, tenant_id, pa, emp)
    # Connected apps hear about the change however it was made: an HR screen, the scheduler on
    # its date, or the sync API (modules/integrations/hooks.py).
    await integration_hooks.personnel_action_applied(session, tenant_id, pa, emp, before)


async def _apply_personnel_action_change(
    session, tenant_id: UUID, pa: PersonnelAction, emp: Employment
) -> None:
    changes = pa.changes or {}
    action_type = PersonnelActionType(pa.type)

    allowed = _ALLOWED_FROM.get(action_type)
    if allowed is not None and emp.employment_state not in allowed:
        state = _STATE_LABEL.get(
            EmploymentState(emp.employment_state), emp.employment_state.lower()
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{_ACTION_LABEL[action_type]} isn't possible while the employee is {state}",
        )

    if action_type in _ASSIGNMENT_ACTIONS:
        current = await _current_assignment(session, tenant_id, pa.employment_id)
        if action_type in _INITIAL_PLACEMENT and current is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This employee already has an active assignment"
            )
        if action_type not in _INITIAL_PLACEMENT and current is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "No active assignment to change — hire them first"
            )
        await _place_assignment(
            session, tenant_id, pa.employment_id, pa.effective_date, changes, current
        )

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
        failure_reason=pa.failure_reason,
    )


async def _validate_assignment_references(session, tenant_id, emp, changes, scope):
    mapping = {
        "org_unit_id": "org_units",
        "location_id": "locations",
        "job_id": "jobs",
        "grade_id": "grades",
        "position_id": "positions",
        "cost_centre_id": "cost_centres",
        "manager_employment_id": "employments",
    }
    for key, table in mapping.items():
        uid = _changed_uuid(changes, key)
        if uid is None:
            continue
        row = (
            (
                await session.execute(
                    text(f"SELECT * FROM {table} WHERE tenant_id = :tid AND id = :id"),
                    {"tid": tenant_id, "id": uid},
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(422, f"Invalid reference: {key}")
        if key == "org_unit_id" and (
            row.get("type") == "DEPARTMENT_TEMPLATE" or row.get("archived_at") is not None
        ):
            raise HTTPException(422, "Assign a company department or team, not a shared department")
        if key in ("org_unit_id", "location_id") and row.get("legal_entity_id") not in (
            None,
            emp.legal_entity_id,
        ):
            raise HTTPException(
                422, "Department and location must belong to the employment's company"
            )
        if key == "manager_employment_id":
            if uid == emp.id:
                raise HTTPException(422, "An employee cannot manage themselves")
            await authorize_employment(session, tenant_id, scope, uid)


async def apply_due_actions(session, tenant_id):
    """
    Apply every SCHEDULED personnel action whose effective date has arrived.

    This runs inside the session dependency, i.e. before EVERY authenticated
    request in the tenant, so an action that cannot be applied must never
    surface as an error there — it would take the whole tenant's API down with
    no way in to fix it. Each action therefore runs in its own SAVEPOINT; one
    that raises is rolled back on its own and parked as FAILED with the reason
    (visible in GET /v1/personnel-actions, cancellable with .../cancel), and the
    rest still apply. The common "nothing is due" path is one indexed SELECT.
    """
    due = (
        await session.execute(
            select(PersonnelAction.id)
            .where(PersonnelAction.tenant_id == tenant_id)
            .where(PersonnelAction.status == PersonnelActionStatus.SCHEDULED)
            .where(PersonnelAction.effective_date <= business_today())
            .limit(1)
        )
    ).first()
    if not due:
        return
    await lock_resource(session, tenant_id, "scheduled-personnel-actions")
    pending = list(
        (
            await session.execute(
                select(PersonnelAction)
                .where(PersonnelAction.tenant_id == tenant_id)
                .where(PersonnelAction.status == PersonnelActionStatus.SCHEDULED)
                .where(PersonnelAction.effective_date <= business_today())
                .order_by(col(PersonnelAction.effective_date), col(PersonnelAction.submitted_at))
                .with_for_update()
            )
        ).scalars()
    )
    for pa in pending:
        action_id, employment_id = pa.id, pa.employment_id
        await lock_resource(session, tenant_id, f"personnel:{employment_id}")
        try:
            async with session.begin_nested():
                emp = (
                    (
                        await session.execute(
                            select(Employment)
                            .where(Employment.tenant_id == tenant_id)
                            .where(Employment.id == employment_id)
                        )
                    )
                    .scalars()
                    .one()
                )
                await _apply_personnel_action(session, tenant_id, pa, emp)
                pa.status = PersonnelActionStatus.APPLIED
                pa.applied_at = datetime.now(UTC)
                session.add(pa)
                await session.flush()
            SCHEDULED_ACTIONS.labels("applied").inc()
        except Exception as exc:
            SCHEDULED_ACTIONS.labels("failed").inc()
            reason = (
                exc.detail if isinstance(exc, HTTPException) and exc.detail else type(exc).__name__
            )[:500]
            logger.warning(
                "Scheduled personnel action %s for employment %s could not be applied: %s",
                action_id,
                employment_id,
                reason,
            )
            # Plain SQL: the savepoint rollback expired the ORM object.
            await session.execute(
                text("""
                    UPDATE personnel_actions
                    SET status = 'FAILED', failure_reason = :reason
                    WHERE tenant_id = :tid AND id = :id
                """),
                {"reason": reason, "tid": tenant_id, "id": action_id},
            )
    await session.flush()

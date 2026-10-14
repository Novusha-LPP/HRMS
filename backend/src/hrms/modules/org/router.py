"""
Organisation module — /v1/org endpoints.

Implements:  legal-entities, locations, org-units (tree), jobs, grades, positions.

Legal entities ARE the sister companies (see core/authz.py) — creating a new
one is a group-level structural change, so it requires org.write AND ALL
scope, not just "some" scope. Listing legal entities/locations/org-units
only returns what the caller's scope covers, so a company-scoped HR manager
can't even see the *names* of companies they don't administer.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, text
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_org_unit, require_permission
from hrms.core.change_audit import record_change
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.core.versioning import require_version
from hrms.modules.kernel.models import EntityChangeLog
from hrms.modules.org.models import (
    CostCentre,
    EmployeeIdScheme,
    Grade,
    Job,
    LegalEntity,
    Location,
    OrgUnit,
    Position,
)
from hrms.modules.org.schemas import (
    AssignDepartmentsRequest,
    ChangeLogEntry,
    CostCentreCreate,
    CostCentreResponse,
    CostCentreUpdate,
    EmployeeIdSchemeCreate,
    EmployeeIdSchemeResponse,
    EmployeeIdSchemeUpdate,
    GradeCreate,
    GradeResponse,
    GradeUpdate,
    JobCreate,
    JobResponse,
    JobUpdate,
    LegalEntityCreate,
    LegalEntityResponse,
    LegalEntityUpdate,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    OrgUnitCreate,
    OrgUnitResponse,
    OrgUnitUpdate,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
)

router = APIRouter(prefix="/v1/org", tags=["Organisation"])


def _entity_scope_ids(scope) -> list[UUID] | None:
    """The concrete legal_entity_ids to filter by, or None to mean 'no filter'."""
    if scope.is_all:
        return None
    return list(scope.legal_entity_ids)


async def _resolve_changer_names(session, tenant_id: UUID, ids: set[UUID]) -> dict[UUID, str]:
    """
    Who made each change, resolved live at read time (never stored) — the
    person's name if the account is tied to an employment, else the login
    email, else the employee code. Same principle as manager_name in
    people/router.py: the id is what's stored, the display value is a join.
    """
    if not ids:
        return {}
    rows = await session.execute(
        text("""
            SELECT ua.id,
                   CASE WHEN ua.status = 'SYSTEM' THEN 'System' ELSE
                   COALESCE(p.legal_first_name || ' ' || p.legal_last_name, ua.email,
                            ua.employee_code) END
            FROM user_accounts ua
            LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
            LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            WHERE ua.tenant_id = CAST(:tid AS uuid) AND ua.id = ANY(CAST(:ids AS uuid[]))
        """),
        {"tid": str(tenant_id), "ids": [str(i) for i in ids]},
    )
    return {r[0]: r[1] for r in rows}


async def _history_response(session, tenant_id: UUID, entries: list) -> list[ChangeLogEntry]:
    names = await _resolve_changer_names(session, tenant_id, {e.changed_by for e in entries})
    return [
        ChangeLogEntry(
            id=to_typed_id("entity_change", e.id),
            action=e.action,
            changes=e.changes,
            changed_by=to_typed_id("user", e.changed_by),
            changed_by_name=names.get(e.changed_by),
            changed_at=e.changed_at,
        )
        for e in entries
    ]


async def _entity_history(session, tenant_id: UUID, entity_type: str, entity_id: UUID):
    rows = await session.execute(
        select(EntityChangeLog)
        .where(EntityChangeLog.tenant_id == tenant_id)
        .where(EntityChangeLog.entity_type == entity_type)
        .where(EntityChangeLog.entity_id == entity_id)
        .order_by(col(EntityChangeLog.changed_at).desc())
    )
    return await _history_response(session, tenant_id, list(rows.scalars()))


# ─── Legal Entities ──────────────────────────────────────────────────────────


@router.post(
    "/legal-entities",
    response_model=LegalEntityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a legal entity",
    dependencies=[require_permission("org.write")],
)
async def create_legal_entity(
    body: LegalEntityCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> LegalEntityResponse:
    scope = scope.for_permission("org.write")
    if not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can add a new company to the tenant",
        )
    uid = uuid4()
    entity = LegalEntity(
        tenant_id=tenant_id,
        id=uid,
        name=body.name,
        short_name=body.short_name,
        country_code=body.country_code,
        establishment_date=body.establishment_date,
        financial_year_start_month=body.financial_year_start_month,
    )
    session.add(entity)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "legal_entity",
        uid,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after=_le_fields(entity),
    )
    return _le_response(entity)


def _le_fields(entity: LegalEntity) -> dict:
    return {
        "name": entity.name,
        "short_name": entity.short_name,
        "country_code": entity.country_code,
        "establishment_date": entity.establishment_date,
        "financial_year_start_month": entity.financial_year_start_month,
    }


def _le_response(entity: LegalEntity) -> LegalEntityResponse:
    return LegalEntityResponse(
        id=to_typed_id("legal_entity", entity.id),
        name=entity.name,
        short_name=entity.short_name,
        country_code=entity.country_code,
        status=entity.status,
        version=entity.version,
        establishment_date=entity.establishment_date,
        financial_year_start_month=entity.financial_year_start_month,
    )


async def _get_legal_entity(session, tenant_id: UUID, entity_id: str) -> LegalEntity:
    uid = to_uuid(entity_id)
    row = await session.execute(
        select(LegalEntity)
        .where(LegalEntity.tenant_id == tenant_id)
        .where(LegalEntity.id == uid)
        .where(col(LegalEntity.archived_at).is_(None))
    )
    entity = row.scalars().first()
    if not entity:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Legal entity not found")
    return entity


@router.patch(
    "/legal-entities/{entity_id}",
    response_model=LegalEntityResponse,
    summary="Rename or reconfigure a legal entity",
    dependencies=[require_permission("org.write")],
)
async def update_legal_entity(
    entity_id: str,
    body: LegalEntityUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> LegalEntityResponse:
    scope = scope.for_permission("org.write")
    if not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can edit a company",
        )
    entity = await _get_legal_entity(session, tenant_id, entity_id)
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    await require_version(session, entity, body.version)
    before = {k: getattr(entity, k) for k in fields}
    for k, v in fields.items():
        setattr(entity, k, v)
    session.add(entity)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "legal_entity",
        entity.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=fields,
    )
    return _le_response(entity)


@router.get(
    "/legal-entities/{entity_id}/history",
    response_model=list[ChangeLogEntry],
    summary="Change history for a legal entity",
)
async def legal_entity_history(
    entity_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[ChangeLogEntry]:
    entity = await _get_legal_entity(session, tenant_id, entity_id)
    if not scope.covers_entity(entity.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")
    return await _entity_history(session, tenant_id, "legal_entity", entity.id)


@router.get(
    "/legal-entities",
    response_model=list[LegalEntityResponse],
    summary="List legal entities visible to the caller",
)
async def list_legal_entities(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[LegalEntityResponse]:
    q = (
        select(LegalEntity)
        .where(LegalEntity.tenant_id == tenant_id)
        .where(col(LegalEntity.archived_at).is_(None))
    )
    ids = _entity_scope_ids(scope)
    if ids is not None:
        if not ids:
            return []
        q = q.where(col(LegalEntity.id).in_(ids))
    rows = await session.execute(q)
    return [_le_response(r) for r in rows.scalars()]


# ─── Locations ───────────────────────────────────────────────────────────────


@router.post(
    "/locations",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a location",
    dependencies=[require_permission("org.write")],
)
async def create_location(
    body: LocationCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> LocationResponse:
    scope = scope.for_permission("org.write")
    uid = uuid4()
    le_uuid: UUID | None = None
    if body.legal_entity_id:
        le_uuid = to_uuid(body.legal_entity_id)
        if not scope.covers_entity(le_uuid):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this legal entity")

    loc = Location(
        tenant_id=tenant_id,
        id=uid,
        name=body.name,
        type=body.type,
        address_line1=body.address_line1,
        city=body.city,
        state_code=body.state_code,
        pincode=body.pincode,
        country_code=body.country_code,
        timezone=body.timezone,
        legal_entity_id=le_uuid,
    )
    session.add(loc)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "location",
        uid,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after=_loc_fields(loc),
    )
    return _loc_response(loc)


def _loc_fields(loc: Location) -> dict:
    return {
        "name": loc.name,
        "type": loc.type,
        "address_line1": loc.address_line1,
        "city": loc.city,
        "state_code": loc.state_code,
        "pincode": loc.pincode,
        "country_code": loc.country_code,
        "timezone": loc.timezone,
    }


def _loc_response(loc: Location) -> LocationResponse:
    return LocationResponse(
        id=to_typed_id("location", loc.id),
        name=loc.name,
        type=loc.type,
        city=loc.city,
        state_code=loc.state_code,
        country_code=loc.country_code,
        timezone=loc.timezone,
        status=loc.status,
        version=loc.version,
        legal_entity_id=to_typed_id("legal_entity", loc.legal_entity_id)
        if loc.legal_entity_id
        else None,
    )


async def _get_location(session, tenant_id: UUID, location_id: str) -> Location:
    uid = to_uuid(location_id)
    row = await session.execute(
        select(Location)
        .where(Location.tenant_id == tenant_id)
        .where(Location.id == uid)
        .where(col(Location.archived_at).is_(None))
    )
    loc = row.scalars().first()
    if not loc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    return loc


@router.patch(
    "/locations/{location_id}",
    response_model=LocationResponse,
    summary="Update a location",
    dependencies=[require_permission("org.write")],
)
async def update_location(
    location_id: str,
    body: LocationUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> LocationResponse:
    scope = scope.for_permission("org.write")
    loc = await _get_location(session, tenant_id, location_id)
    if loc.legal_entity_id and not scope.covers_entity(loc.legal_entity_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this legal entity")
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    await require_version(session, loc, body.version)
    before = {k: getattr(loc, k) for k in fields}
    for k, v in fields.items():
        setattr(loc, k, v)
    session.add(loc)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "location",
        loc.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=fields,
    )
    return _loc_response(loc)


@router.get(
    "/locations/{location_id}/history",
    response_model=list[ChangeLogEntry],
    summary="Change history for a location",
)
async def location_history(
    location_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[ChangeLogEntry]:
    loc = await _get_location(session, tenant_id, location_id)
    if loc.legal_entity_id and not scope.covers_entity(loc.legal_entity_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this legal entity")
    return await _entity_history(session, tenant_id, "location", loc.id)


@router.get(
    "/locations",
    response_model=list[LocationResponse],
    summary="List locations visible to the caller",
)
async def list_locations(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[LocationResponse]:
    ids = _entity_scope_ids(scope)
    if ids is not None and not ids:
        return []
    rows = None
    if ids is None:
        rows = await session.execute(
            select(Location)
            .where(Location.tenant_id == tenant_id)
            .where(col(Location.archived_at).is_(None))
        )
    else:
        # Tenant-wide locations (legal_entity_id IS NULL) stay visible to everyone.
        result = await session.execute(
            text("""
                SELECT id FROM locations
                WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
                  AND (legal_entity_id IS NULL OR legal_entity_id = ANY(CAST(:ids AS uuid[])))
            """),
            {"tid": str(tenant_id), "ids": [str(i) for i in ids]},
        )
        loc_ids = [r[0] for r in result]
        rows = (
            await session.execute(select(Location).where(col(Location.id).in_(loc_ids)))
            if loc_ids
            else None
        )
    scalars: list[Location] = list(rows.scalars()) if rows is not None else []
    return [_loc_response(r) for r in scalars]


# ─── Org Units ────────────────────────────────────────────────────────────────


@router.post(
    "/org-units",
    response_model=OrgUnitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an org unit",
    dependencies=[require_permission("org.write")],
)
async def create_org_unit(
    body: OrgUnitCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> OrgUnitResponse:
    scope = scope.for_permission("org.write")
    uid = uuid4()
    parent_uuid: UUID | None = None
    if body.parent_id:
        parent_uuid = to_uuid(body.parent_id)
    le_uuid: UUID | None = None
    if body.legal_entity_id:
        le_uuid = to_uuid(body.legal_entity_id)
        if not scope.covers_entity(le_uuid):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this legal entity")
    if body.type == "DEPARTMENT_TEMPLATE":
        if not scope.is_all:
            raise HTTPException(403, "Only a group administrator can manage shared departments")
        if le_uuid or parent_uuid:
            raise HTTPException(422, "Shared departments are defined before assigning a company")
        if not body.name.strip():
            raise HTTPException(422, "Department name is required")
        await lock_resource(session, tenant_id, "department-catalog")
        duplicate = await session.execute(
            select(OrgUnit).where(
                OrgUnit.tenant_id == tenant_id,
                OrgUnit.type == "DEPARTMENT_TEMPLATE",
                col(OrgUnit.archived_at).is_(None),
                func.lower(col(OrgUnit.name)) == body.name.strip().lower(),
            )
        )
        if duplicate.scalars().first():
            raise HTTPException(409, "A shared department with this name already exists")
    if body.type == "TEAM":
        if not body.parent_id:
            raise HTTPException(422, "A team must belong to a department")
        parent = await _get_org_unit(session, tenant_id, body.parent_id)
        if parent.type != "DEPARTMENT":
            raise HTTPException(422, "A team's parent must be a department")
        if parent.legal_entity_id != le_uuid:
            raise HTTPException(422, "A team must belong to the same company as its department")
    loc_uuid: UUID | None = None
    if body.location_id:
        loc_uuid = to_uuid(body.location_id)

    roles = await _team_roles(session, tenant_id, body.type, le_uuid, body.model_dump())
    unit = OrgUnit(
        **roles,
        tenant_id=tenant_id,
        id=uid,
        name=body.name.strip(),
        code=body.code,
        type=body.type,
        parent_id=parent_uuid,
        legal_entity_id=le_uuid,
        location_id=loc_uuid,
        effective_from=body.effective_from,
    )
    session.add(unit)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "org_unit",
        uid,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after={"name": unit.name, "code": unit.code, "type": unit.type, **roles},
    )
    return _ou_response(unit)


def _ou_response(unit: OrgUnit) -> OrgUnitResponse:
    return OrgUnitResponse(
        id=to_typed_id("org_unit", unit.id),
        name=unit.name,
        code=unit.code,
        type=unit.type,
        parent_id=to_typed_id("org_unit", unit.parent_id) if unit.parent_id else None,
        department_template_id=to_typed_id("org_unit", unit.department_template_id)
        if unit.department_template_id
        else None,
        legal_entity_id=to_typed_id("legal_entity", unit.legal_entity_id)
        if unit.legal_entity_id
        else None,
        head_employment_id=to_typed_id("employment", unit.head_employment_id)
        if unit.head_employment_id
        else None,
        lead_employment_id=to_typed_id("employment", unit.lead_employment_id)
        if unit.lead_employment_id
        else None,
        pm_employment_id=to_typed_id("employment", unit.pm_employment_id)
        if unit.pm_employment_id
        else None,
        status=unit.status,
        effective_from=unit.effective_from,
        effective_to=unit.effective_to,
        version=unit.version,
    )


async def _team_roles(session, tenant_id, kind, entity_id, fields):
    roles = {}
    for key in ("head_employment_id", "lead_employment_id", "pm_employment_id"):
        if key not in fields:
            continue
        value = fields[key]
        expected = "DEPARTMENT" if key == "head_employment_id" else "TEAM"
        if value and kind != expected:
            raise HTTPException(422, "Assign HODs to departments and leads/PMs to teams")
        uid = to_uuid(value) if value else None
        if uid:
            row = (
                await session.execute(
                    text("""
                SELECT id FROM employments WHERE tenant_id=:tid AND id=:eid
                AND legal_entity_id=:company AND archived_at IS NULL
                AND employment_state<>'SEPARATED'
            """),
                    dict(tid=tenant_id, eid=uid, company=entity_id),
                )
            ).first()
            if not row:
                raise HTTPException(
                    422, "Department heads, leads and PMs must be active employees of this company"
                )
        roles[key] = uid
    return roles


async def _get_org_unit(session, tenant_id: UUID, unit_id: str) -> OrgUnit:
    uid = to_uuid(unit_id)
    row = await session.execute(
        select(OrgUnit)
        .where(OrgUnit.tenant_id == tenant_id)
        .where(OrgUnit.id == uid)
        .where(col(OrgUnit.archived_at).is_(None))
    )
    unit = row.scalars().first()
    if not unit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Org unit not found")
    return unit


@router.post(
    "/legal-entities/{entity_id}/departments",
    response_model=list[OrgUnitResponse],
    dependencies=[require_permission("org.write")],
    summary="Assign shared departments to a company",
)
async def assign_departments(
    entity_id: str,
    body: AssignDepartmentsRequest,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[OrgUnitResponse]:
    scope = scope.for_permission("org.write")
    entity_uuid = to_uuid(entity_id)
    if not scope.covers_entity(entity_uuid):
        raise HTTPException(403, "Not authorized for this company")
    await _get_legal_entity(session, tenant_id, entity_id)
    await lock_resource(session, tenant_id, "department-catalog")
    await lock_resource(session, tenant_id, f"company-departments:{entity_uuid}")
    templates = []
    for template_id in dict.fromkeys(body.department_ids):
        template = await _get_org_unit(session, tenant_id, template_id)
        if template.type != "DEPARTMENT_TEMPLATE":
            raise HTTPException(422, "Select a department from the shared department list")
        templates.append(template)
    assigned = []
    for template in templates:
        result = await session.execute(
            select(OrgUnit).where(
                OrgUnit.tenant_id == tenant_id,
                OrgUnit.legal_entity_id == entity_uuid,
                OrgUnit.department_template_id == template.id,
                col(OrgUnit.archived_at).is_(None),
            )
        )
        existing = result.scalars().first()
        if existing:
            assigned.append(_ou_response(existing))
            continue
        unit = OrgUnit(
            tenant_id=tenant_id,
            id=uuid4(),
            name=template.name,
            code=template.code,
            type="DEPARTMENT",
            legal_entity_id=entity_uuid,
            department_template_id=template.id,
            effective_from=business_today(),
        )
        session.add(unit)
        await session.flush()
        await record_change(
            session,
            tenant_id,
            "org_unit",
            unit.id,
            "CREATE",
            changed_by=principal.user_account_id,
            before=None,
            after={
                "name": unit.name,
                "code": unit.code,
                "type": unit.type,
                "department_template_id": template.id,
                "legal_entity_id": entity_uuid,
            },
        )
        assigned.append(_ou_response(unit))
    return assigned


@router.patch(
    "/org-units/{unit_id}",
    response_model=OrgUnitResponse,
    summary="Rename or recode an org unit",
    dependencies=[require_permission("org.write")],
)
async def update_org_unit(
    unit_id: str,
    body: OrgUnitUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> OrgUnitResponse:
    scope = scope.for_permission("org.write")
    unit = await _get_org_unit(session, tenant_id, unit_id)
    if unit.legal_entity_id and not scope.covers_entity(unit.legal_entity_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this legal entity")
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    if unit.type == "DEPARTMENT_TEMPLATE":
        if not scope.is_all:
            raise HTTPException(403, "Only a group administrator can manage shared departments")
        if "type" in fields and fields["type"] != unit.type:
            raise HTTPException(422, "A shared department's type cannot be changed")
        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise HTTPException(422, "Department name is required")
            fields["name"] = name
            await lock_resource(session, tenant_id, "department-catalog")
            duplicate = await session.execute(
                select(OrgUnit).where(
                    OrgUnit.tenant_id == tenant_id,
                    OrgUnit.type == "DEPARTMENT_TEMPLATE",
                    OrgUnit.id != unit.id,
                    col(OrgUnit.archived_at).is_(None),
                    func.lower(col(OrgUnit.name)) == name.lower(),
                )
            )
            if duplicate.scalars().first():
                raise HTTPException(409, "A shared department with this name already exists")
    elif unit.department_template_id and any(k != "head_employment_id" for k in fields):
        raise HTTPException(409, "Edit this department in the shared department list")
    fields.update(
        await _team_roles(
            session, tenant_id, fields.get("type", unit.type), unit.legal_entity_id, fields
        )
    )
    await require_version(session, unit, body.version)
    before = {k: getattr(unit, k) for k in fields}
    for k, v in fields.items():
        setattr(unit, k, v)
    session.add(unit)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "org_unit",
        unit.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=fields,
    )
    if unit.type == "DEPARTMENT_TEMPLATE":
        linked = await session.execute(
            select(OrgUnit).where(
                OrgUnit.tenant_id == tenant_id,
                OrgUnit.department_template_id == unit.id,
                col(OrgUnit.archived_at).is_(None),
            )
        )
        updates = {k: v for k, v in fields.items() if k in ("name", "code")}
        for company_department in linked.scalars():
            old = {k: getattr(company_department, k) for k in updates}
            for k, v in updates.items():
                setattr(company_department, k, v)
            session.add(company_department)
            await record_change(
                session,
                tenant_id,
                "org_unit",
                company_department.id,
                "UPDATE",
                changed_by=principal.user_account_id,
                before=old,
                after=updates,
            )
        await session.flush()
    return _ou_response(unit)


@router.get(
    "/org-units/{unit_id}/history",
    response_model=list[ChangeLogEntry],
    summary="Change history for an org unit",
)
async def org_unit_history(
    unit_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[ChangeLogEntry]:
    unit = await _get_org_unit(session, tenant_id, unit_id)
    if unit.legal_entity_id and not scope.covers_entity(unit.legal_entity_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this legal entity")
    return await _entity_history(session, tenant_id, "org_unit", unit.id)


@router.get(
    "/org-units",
    response_model=list[OrgUnitResponse],
    summary="List org units visible to the caller",
)
async def list_org_units(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[OrgUnitResponse]:
    ids = _entity_scope_ids(scope)
    if ids is not None and not ids:
        return []
    if ids is None:
        rows = await session.execute(
            select(OrgUnit)
            .where(OrgUnit.tenant_id == tenant_id)
            .where(col(OrgUnit.archived_at).is_(None))
        )
        scalars = list(rows.scalars())
    else:
        result = await session.execute(
            text("""
                SELECT id FROM org_units
                WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
                  AND (legal_entity_id IS NULL OR legal_entity_id = ANY(CAST(:ids AS uuid[])))
            """),
            {"tid": str(tenant_id), "ids": [str(i) for i in ids]},
        )
        unit_ids = [r[0] for r in result]
        scalars = (
            list(
                (
                    await session.execute(select(OrgUnit).where(col(OrgUnit.id).in_(unit_ids)))
                ).scalars()
            )
            if unit_ids
            else []
        )
    return [_ou_response(r) for r in scalars]


# ─── Jobs (tenant-wide catalog — no per-company scoping) ──────────────────────


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a job",
    dependencies=[require_permission("org.write")],
)
async def create_job(
    body: JobCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> JobResponse:
    uid = uuid4()
    job = Job(
        tenant_id=tenant_id,
        id=uid,
        title=body.title,
        code=body.code,
        function=body.function,
    )
    session.add(job)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "job",
        uid,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after={"title": job.title, "code": job.code, "function": job.function},
    )
    return _job_response(job)


def _job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=to_typed_id("job", job.id),
        title=job.title,
        code=job.code,
        function=job.function,
        status=job.status,
        version=job.version,
    )


async def _get_job(session, tenant_id: UUID, job_id: str) -> Job:
    uid = to_uuid(job_id)
    row = await session.execute(
        select(Job)
        .where(Job.tenant_id == tenant_id)
        .where(Job.id == uid)
        .where(col(Job.archived_at).is_(None))
    )
    job = row.scalars().first()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("/jobs", response_model=list[JobResponse], summary="List jobs")
async def list_jobs(
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[JobResponse]:
    rows = await session.execute(
        select(Job).where(col(Job.tenant_id) == tenant_id).where(col(Job.archived_at).is_(None))
    )
    return [_job_response(r) for r in rows.scalars()]


@router.patch(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Update a job title",
    dependencies=[require_permission("org.write")],
)
async def update_job(
    job_id: str,
    body: JobUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> JobResponse:
    job = await _get_job(session, tenant_id, job_id)
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    await require_version(session, job, body.version)
    before = {k: getattr(job, k) for k in fields}
    for k, v in fields.items():
        setattr(job, k, v)
    session.add(job)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "job",
        job.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=fields,
    )
    return _job_response(job)


@router.get(
    "/jobs/{job_id}/history",
    response_model=list[ChangeLogEntry],
    summary="Change history for a job",
)
async def job_history(
    job_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[ChangeLogEntry]:
    job = await _get_job(session, tenant_id, job_id)
    return await _entity_history(session, tenant_id, "job", job.id)


# ─── Grades and cost centres (tenant-wide catalogs, like jobs) ────────────────
#
# Never deleted: a grade or cost centre on someone's history must stay readable,
# so retiring one is status=INACTIVE. Codes are unique per tenant, ignoring case.


async def _ensure_unique_code(session, tenant_id: UUID, model, code: str, label: str, exclude=None):
    q = (
        select(model.id)
        .where(model.tenant_id == tenant_id)
        .where(func.lower(model.code) == code.lower())
        .where(col(model.archived_at).is_(None))
    )
    if exclude is not None:
        q = q.where(model.id != exclude)
    if (await session.execute(q)).first():
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A {label} with code {code!r} already exists"
        )


async def _get_catalog_row(session, tenant_id: UUID, model, typed_id: str, label: str):
    row = await session.execute(
        select(model)
        .where(model.tenant_id == tenant_id)
        .where(model.id == to_uuid(typed_id))
        .where(col(model.archived_at).is_(None))
    )
    found = row.scalars().first()
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    return found


def _set_fields(fields: dict, nullable: frozenset[str] = frozenset()) -> dict:
    """PATCH values to apply: strings trimmed, and null ignored where the column can't be null."""
    out = {}
    for k, v in fields.items():
        if v is None and k not in nullable:
            continue
        out[k] = v.strip() if isinstance(v, str) else v
    return out


def _grade_response(g: Grade) -> GradeResponse:
    return GradeResponse(
        id=to_typed_id("grade", g.id),
        code=g.code,
        name=g.name,
        sequence=g.sequence,
        status=g.status,
        version=g.version,
    )


@router.get("/grades", response_model=list[GradeResponse], summary="List grades")
async def list_grades(tenant_id: TenantDep, session: SessionDep) -> list[GradeResponse]:
    rows = await session.execute(
        select(Grade)
        .where(Grade.tenant_id == tenant_id)
        .where(col(Grade.archived_at).is_(None))
        .order_by(col(Grade.sequence), col(Grade.code))
    )
    return [_grade_response(g) for g in rows.scalars()]


@router.post(
    "/grades",
    response_model=GradeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a grade",
    dependencies=[require_permission("org.write")],
)
async def create_grade(
    body: GradeCreate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> GradeResponse:
    code = body.code.strip()
    await _ensure_unique_code(session, tenant_id, Grade, code, "grade")
    grade = Grade(
        tenant_id=tenant_id, id=uuid4(), code=code, name=body.name.strip(), sequence=body.sequence
    )
    session.add(grade)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "grade",
        grade.id,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after={"code": grade.code, "name": grade.name, "sequence": grade.sequence},
    )
    return _grade_response(grade)


@router.patch(
    "/grades/{grade_id}",
    response_model=GradeResponse,
    summary="Update a grade",
    dependencies=[require_permission("org.write")],
)
async def update_grade(
    grade_id: str,
    body: GradeUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> GradeResponse:
    grade = await _get_catalog_row(session, tenant_id, Grade, grade_id, "Grade")
    fields = _set_fields(body.model_dump(exclude_unset=True, exclude={"version"}))
    if "code" in fields:
        await _ensure_unique_code(session, tenant_id, Grade, fields["code"], "grade", grade.id)
    await require_version(session, grade, body.version)
    before = {k: getattr(grade, k) for k in fields}
    for k, v in fields.items():
        setattr(grade, k, v)
    session.add(grade)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "grade",
        grade.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=fields,
    )
    return _grade_response(grade)


@router.get(
    "/grades/{grade_id}/history",
    response_model=list[ChangeLogEntry],
    summary="Change history for a grade",
)
async def grade_history(
    grade_id: str, tenant_id: TenantDep, session: SessionDep
) -> list[ChangeLogEntry]:
    grade = await _get_catalog_row(session, tenant_id, Grade, grade_id, "Grade")
    return await _entity_history(session, tenant_id, "grade", grade.id)


def _cost_centre_response(c: CostCentre) -> CostCentreResponse:
    return CostCentreResponse(
        id=to_typed_id("cost_centre", c.id),
        code=c.code,
        name=c.name,
        status=c.status,
        version=c.version,
    )


@router.get("/cost-centres", response_model=list[CostCentreResponse], summary="List cost centres")
async def list_cost_centres(tenant_id: TenantDep, session: SessionDep) -> list[CostCentreResponse]:
    rows = await session.execute(
        select(CostCentre)
        .where(CostCentre.tenant_id == tenant_id)
        .where(col(CostCentre.archived_at).is_(None))
        .order_by(col(CostCentre.code))
    )
    return [_cost_centre_response(c) for c in rows.scalars()]


@router.post(
    "/cost-centres",
    response_model=CostCentreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a cost centre",
    dependencies=[require_permission("org.write")],
)
async def create_cost_centre(
    body: CostCentreCreate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> CostCentreResponse:
    code = body.code.strip()
    await _ensure_unique_code(session, tenant_id, CostCentre, code, "cost centre")
    centre = CostCentre(tenant_id=tenant_id, id=uuid4(), code=code, name=body.name.strip())
    session.add(centre)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "cost_centre",
        centre.id,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after={"code": centre.code, "name": centre.name},
    )
    return _cost_centre_response(centre)


@router.patch(
    "/cost-centres/{cost_centre_id}",
    response_model=CostCentreResponse,
    summary="Update a cost centre",
    dependencies=[require_permission("org.write")],
)
async def update_cost_centre(
    cost_centre_id: str,
    body: CostCentreUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> CostCentreResponse:
    centre = await _get_catalog_row(session, tenant_id, CostCentre, cost_centre_id, "Cost centre")
    fields = _set_fields(body.model_dump(exclude_unset=True, exclude={"version"}))
    if "code" in fields:
        await _ensure_unique_code(
            session, tenant_id, CostCentre, fields["code"], "cost centre", centre.id
        )
    await require_version(session, centre, body.version)
    before = {k: getattr(centre, k) for k in fields}
    for k, v in fields.items():
        setattr(centre, k, v)
    session.add(centre)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "cost_centre",
        centre.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=fields,
    )
    return _cost_centre_response(centre)


@router.get(
    "/cost-centres/{cost_centre_id}/history",
    response_model=list[ChangeLogEntry],
    summary="Change history for a cost centre",
)
async def cost_centre_history(
    cost_centre_id: str, tenant_id: TenantDep, session: SessionDep
) -> list[ChangeLogEntry]:
    centre = await _get_catalog_row(session, tenant_id, CostCentre, cost_centre_id, "Cost centre")
    return await _entity_history(session, tenant_id, "cost_centre", centre.id)


# ─── Positions (seats in a company department or team) ───────────────────────
#
# A position belongs to one org unit, so it is scoped like that unit's company.
# `filled` counts current, non-separated employees placed in it, the same count the
# HR dashboard's vacancies card uses (status ACTIVE and a max_headcount set).

_POSITION_SELECT = """
    SELECT p.id, p.title, p.code, p.org_unit_id, ou.name AS org_unit_name, ou.legal_entity_id,
           p.job_id, j.title AS job_title, p.grade_id, g.name AS grade_name, p.max_headcount,
           p.status, p.effective_from, p.effective_to, p.version, COALESCE(filled.n, 0) AS filled
    FROM positions p
    JOIN org_units ou ON ou.tenant_id = p.tenant_id AND ou.id = p.org_unit_id
    LEFT JOIN jobs j ON j.tenant_id = p.tenant_id AND j.id = p.job_id
    LEFT JOIN grades g ON g.tenant_id = p.tenant_id AND g.id = p.grade_id
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS n FROM assignments a
        JOIN employments e ON e.tenant_id = a.tenant_id AND e.id = a.employment_id
        WHERE a.tenant_id = p.tenant_id AND a.position_id = p.id
          AND a.effective_from <= CAST(:today AS date)
          AND (a.effective_to IS NULL OR a.effective_to > CAST(:today AS date))
          AND e.employment_state != 'SEPARATED'
    ) filled ON true
    WHERE p.tenant_id = CAST(:tid AS uuid) AND p.archived_at IS NULL
"""


def _position_scope_sql(scope) -> tuple[str, dict]:
    if scope.is_all:
        return "", {}
    clauses, params = [], {}
    if scope.legal_entity_ids:
        clauses.append("ou.legal_entity_id = ANY(CAST(:pos_entities AS uuid[]))")
        params["pos_entities"] = [str(i) for i in scope.legal_entity_ids]
    if scope.org_unit_ids:
        clauses.append("p.org_unit_id = ANY(CAST(:pos_units AS uuid[]))")
        params["pos_units"] = [str(i) for i in scope.org_unit_ids]
    if not clauses:
        return " AND FALSE", {}
    return " AND (" + " OR ".join(clauses) + ")", params


def _position_response(r) -> PositionResponse:
    filled = int(r["filled"])
    limit = r["max_headcount"]
    return PositionResponse(
        id=to_typed_id("position", r["id"]),
        title=r["title"],
        code=r["code"],
        org_unit_id=to_typed_id("org_unit", r["org_unit_id"]),
        org_unit_name=r["org_unit_name"],
        legal_entity_id=to_typed_id("legal_entity", r["legal_entity_id"])
        if r["legal_entity_id"]
        else None,
        job_id=to_typed_id("job", r["job_id"]) if r["job_id"] else None,
        job_title=r["job_title"],
        grade_id=to_typed_id("grade", r["grade_id"]) if r["grade_id"] else None,
        grade_name=r["grade_name"],
        max_headcount=limit,
        filled=filled,
        vacancies=max(limit - filled, 0) if limit is not None else None,
        status=r["status"],
        effective_from=r["effective_from"],
        effective_to=r["effective_to"],
        version=r["version"],
    )


async def _position_row(session, tenant_id: UUID, position_id: UUID):
    row = await session.execute(
        text(_POSITION_SELECT + " AND p.id = CAST(:pid AS uuid)"),
        {"tid": str(tenant_id), "pid": str(position_id), "today": business_today()},
    )
    found = row.mappings().first()
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    return found


async def _optional_ref(session, tenant_id: UUID, model, typed_id: str | None, label: str):
    """Resolve an optional reference (job, grade) to a UUID, 422 if it doesn't exist."""
    if not typed_id:
        return None
    uid = to_uuid(typed_id)
    exists = await session.execute(
        select(model.id)
        .where(model.tenant_id == tenant_id)
        .where(model.id == uid)
        .where(col(model.archived_at).is_(None))
    )
    if not exists.first():
        raise HTTPException(422, f"{label} not found")
    return uid


@router.get("/positions", response_model=list[PositionResponse], summary="List positions")
async def list_positions(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    org_unit_id: str | None = None,
) -> list[PositionResponse]:
    scope_sql, params = _position_scope_sql(scope)
    sql = _POSITION_SELECT + scope_sql
    if org_unit_id:
        sql += " AND p.org_unit_id = CAST(:ou AS uuid)"
        params["ou"] = str(to_uuid(org_unit_id))
    rows = await session.execute(
        text(sql + " ORDER BY ou.name, p.title"),
        {"tid": str(tenant_id), "today": business_today(), **params},
    )
    return [_position_response(r) for r in rows.mappings()]


@router.post(
    "/positions",
    response_model=PositionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a position",
    dependencies=[require_permission("org.write")],
)
async def create_position(
    body: PositionCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> PositionResponse:
    unit = (
        (
            await session.execute(
                select(OrgUnit)
                .where(OrgUnit.tenant_id == tenant_id)
                .where(OrgUnit.id == to_uuid(body.org_unit_id))
                .where(col(OrgUnit.archived_at).is_(None))
            )
        )
        .scalars()
        .first()
    )
    if not unit:
        raise HTTPException(422, "Department not found")
    if unit.type == "DEPARTMENT_TEMPLATE":
        raise HTTPException(
            422,
            "Choose a company's department or team, not a shared department",
        )
    await authorize_org_unit(session, tenant_id, scope, unit.id)
    job_id = await _optional_ref(session, tenant_id, Job, body.job_id, "Job")
    grade_id = await _optional_ref(session, tenant_id, Grade, body.grade_id, "Grade")
    start = body.effective_from or business_today()
    if body.effective_to is not None and body.effective_to <= start:
        raise HTTPException(422, "The end date must be after the start date")
    position = Position(
        tenant_id=tenant_id,
        id=uuid4(),
        title=body.title.strip(),
        code=(body.code or "").strip() or None,
        org_unit_id=unit.id,
        job_id=job_id,
        grade_id=grade_id,
        max_headcount=body.max_headcount,
        # ACTIVE, not the model's historical "OPEN" default: the dashboard's vacancy
        # count only reads ACTIVE positions.
        status="ACTIVE",
        effective_from=start,
        effective_to=body.effective_to,
    )
    session.add(position)
    await session.flush()
    row = await _position_row(session, tenant_id, position.id)
    await record_change(
        session,
        tenant_id,
        "position",
        position.id,
        "CREATE",
        changed_by=principal.user_account_id,
        before=None,
        after=_position_history_values(row, _POSITION_HISTORY_FIELDS),
    )
    return _position_response(row)


# History shows what HR reads on screen (department, job and grade names as they were at
# the time), not the IDs behind them.
_POSITION_HISTORY_FIELDS = (
    "title",
    "code",
    "department",
    "job",
    "grade",
    "max_headcount",
    "status",
    "effective_from",
    "effective_to",
)
_POSITION_HISTORY_SOURCE = {
    "department": "org_unit_name",
    "job": "job_title",
    "grade": "grade_name",
}
_POSITION_FIELD_LABEL = {"job_id": "job", "grade_id": "grade"}


def _position_history_values(row, labels) -> dict:
    return {label: row[_POSITION_HISTORY_SOURCE.get(label, label)] for label in labels}


async def _get_position(session, tenant_id: UUID, scope, position_id: str) -> Position:
    position = (
        (
            await session.execute(
                select(Position)
                .where(Position.tenant_id == tenant_id)
                .where(Position.id == to_uuid(position_id))
                .where(col(Position.archived_at).is_(None))
            )
        )
        .scalars()
        .first()
    )
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    await authorize_org_unit(session, tenant_id, scope, position.org_unit_id)
    return position


@router.patch(
    "/positions/{position_id}",
    response_model=PositionResponse,
    summary="Update a position",
    dependencies=[require_permission("org.write")],
)
async def update_position(
    position_id: str,
    body: PositionUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> PositionResponse:
    position = await _get_position(session, tenant_id, scope, position_id)
    fields = _set_fields(
        body.model_dump(exclude_unset=True, exclude={"version"}),
        nullable=frozenset({"code", "job_id", "grade_id", "max_headcount", "effective_to"}),
    )
    if "code" in fields:
        fields["code"] = fields["code"] or None
    if "job_id" in fields:
        fields["job_id"] = await _optional_ref(session, tenant_id, Job, fields["job_id"], "Job")
    if "grade_id" in fields:
        fields["grade_id"] = await _optional_ref(
            session, tenant_id, Grade, fields["grade_id"], "Grade"
        )
    end = fields.get("effective_to", position.effective_to)
    if end is not None and end <= position.effective_from:
        raise HTTPException(422, "The end date must be after the start date")
    labels = [_POSITION_FIELD_LABEL.get(k, k) for k in fields]
    await require_version(session, position, body.version)
    before = _position_history_values(await _position_row(session, tenant_id, position.id), labels)
    for k, v in fields.items():
        setattr(position, k, v)
    session.add(position)
    await session.flush()
    row = await _position_row(session, tenant_id, position.id)
    await record_change(
        session,
        tenant_id,
        "position",
        position.id,
        "UPDATE",
        changed_by=principal.user_account_id,
        before=before,
        after=_position_history_values(row, labels),
    )
    return _position_response(row)


@router.get(
    "/positions/{position_id}/history",
    response_model=list[ChangeLogEntry],
    summary="Change history for a position",
)
async def position_history(
    position_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> list[ChangeLogEntry]:
    position = await _get_position(session, tenant_id, scope, position_id)
    return await _entity_history(session, tenant_id, "position", position.id)


# ─── Employee ID schemes ──────────────────────────────────────────────────────
#
# Configurable employee-number generation (prefix + running number), either
# tenant-wide or per legal entity — see EmployeeIdScheme's docstring for the
# resolution order. Setting the tenant-wide scheme is a group-level change
# (same bar as creating a legal entity); setting a company's own scheme only
# needs that company within the caller's scope.


@router.get(
    "/employee-id-schemes",
    response_model=list[EmployeeIdSchemeResponse],
    summary="List employee ID schemes visible to the caller",
)
async def list_employee_id_schemes(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[EmployeeIdSchemeResponse]:
    q = (
        select(EmployeeIdScheme, LegalEntity.name)
        .outerjoin(LegalEntity, col(LegalEntity.id) == col(EmployeeIdScheme.legal_entity_id))
        .where(EmployeeIdScheme.tenant_id == tenant_id)
        .where(col(EmployeeIdScheme.archived_at).is_(None))
    )
    ids = _entity_scope_ids(scope)
    if ids is not None:
        if not ids:
            return []
        # A scoped caller sees their own companies' schemes, plus the
        # tenant-wide one (legal_entity_id IS NULL) if it exists — they're
        # affected by it even though they can't create it.
        q = q.where(
            (col(EmployeeIdScheme.legal_entity_id).in_(ids))
            | (col(EmployeeIdScheme.legal_entity_id).is_(None))
        )
    rows = await session.execute(q)
    return [_eis_response(s, name) for s, name in rows]


@router.post(
    "/employee-id-schemes",
    response_model=EmployeeIdSchemeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an employee ID scheme (tenant-wide or for one company)",
    dependencies=[require_permission("org.write")],
)
async def create_employee_id_scheme(
    body: EmployeeIdSchemeCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> EmployeeIdSchemeResponse:
    scope = scope.for_permission("org.write")
    le_uuid: UUID | None = None
    le_name: str | None = None
    if body.legal_entity_id:
        le_uuid = to_uuid(body.legal_entity_id)
        if not scope.covers_entity(le_uuid):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")
        le_row = await session.execute(
            select(LegalEntity)
            .where(LegalEntity.tenant_id == tenant_id)
            .where(LegalEntity.id == le_uuid)
        )
        le = le_row.scalars().first()
        if not le:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
        le_name = le.name
    elif not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can set the tenant-wide employee ID scheme",
        )

    existing = await session.execute(
        select(EmployeeIdScheme)
        .where(EmployeeIdScheme.tenant_id == tenant_id)
        .where(col(EmployeeIdScheme.archived_at).is_(None))
        .where(EmployeeIdScheme.legal_entity_id == le_uuid)
    )
    if existing.scalars().first():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An active employee ID scheme already exists — edit or remove it first",
        )

    uid = uuid4()
    scheme = EmployeeIdScheme(
        tenant_id=tenant_id,
        id=uid,
        legal_entity_id=le_uuid,
        prefix=body.prefix,
        separator=body.separator,
        number_digits=body.number_digits,
        next_number=body.next_number,
    )
    session.add(scheme)
    await session.flush()
    return _eis_response(scheme, le_name)


@router.patch(
    "/employee-id-schemes/{scheme_id}",
    response_model=EmployeeIdSchemeResponse,
    summary="Update an employee ID scheme",
    dependencies=[require_permission("org.write")],
)
async def update_employee_id_scheme(
    scheme_id: str,
    body: EmployeeIdSchemeUpdate,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> EmployeeIdSchemeResponse:
    scope = scope.for_permission("org.write")
    scheme, le_name = await _get_eis(session, tenant_id, scheme_id)
    if scheme.legal_entity_id:
        if not scope.covers_entity(scheme.legal_entity_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")
    elif not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can change the tenant-wide employee ID scheme",
        )
    await require_version(session, scheme, body.version)
    for k, v in body.model_dump(exclude_unset=True, exclude={"version"}).items():
        setattr(scheme, k, v)
    session.add(scheme)
    await session.flush()
    return _eis_response(scheme, le_name)


@router.delete(
    "/employee-id-schemes/{scheme_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an employee ID scheme",
    dependencies=[require_permission("org.write")],
)
async def delete_employee_id_scheme(
    scheme_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> None:
    scope = scope.for_permission("org.write")
    scheme, _ = await _get_eis(session, tenant_id, scheme_id)
    if scheme.legal_entity_id:
        if not scope.covers_entity(scheme.legal_entity_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")
    elif not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can remove the tenant-wide employee ID scheme",
        )
    scheme.archived_at = now_utc()
    session.add(scheme)


def _eis_response(s: EmployeeIdScheme, legal_entity_name: str | None) -> EmployeeIdSchemeResponse:
    return EmployeeIdSchemeResponse(
        version=s.version,
        id=to_typed_id("employee_id_scheme", s.id),
        legal_entity_id=to_typed_id("legal_entity", s.legal_entity_id)
        if s.legal_entity_id
        else None,
        legal_entity_name=legal_entity_name,
        prefix=s.prefix,
        separator=s.separator,
        number_digits=s.number_digits,
        next_number=s.next_number,
        preview=f"{s.prefix}{s.separator}{str(s.next_number).zfill(s.number_digits)}",
    )


async def _get_eis(session, tenant_id, scheme_id: str) -> tuple[EmployeeIdScheme, str | None]:
    uid = to_uuid(scheme_id)
    row = await session.execute(
        select(EmployeeIdScheme, LegalEntity.name)
        .outerjoin(LegalEntity, col(LegalEntity.id) == col(EmployeeIdScheme.legal_entity_id))
        .where(EmployeeIdScheme.tenant_id == tenant_id)
        .where(EmployeeIdScheme.id == uid)
    )
    result = row.first()
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee ID scheme not found")
    return result

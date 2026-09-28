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
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authz import ScopeDep, require_permission
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.org.models import EmployeeIdScheme, Job, LegalEntity, Location, OrgUnit
from hrms.modules.org.schemas import (
    EmployeeIdSchemeCreate,
    EmployeeIdSchemeResponse,
    EmployeeIdSchemeUpdate,
    JobCreate,
    JobResponse,
    LegalEntityCreate,
    LegalEntityResponse,
    LocationCreate,
    LocationResponse,
    OrgUnitCreate,
    OrgUnitResponse,
)

router = APIRouter(prefix="/v1/org", tags=["Organisation"])


def _entity_scope_ids(scope) -> list[UUID] | None:
    """The concrete legal_entity_ids to filter by, or None to mean 'no filter'."""
    if scope.is_all:
        return None
    return list(scope.legal_entity_ids)


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
    )
    session.add(entity)
    await session.flush()
    return LegalEntityResponse(
        id=to_typed_id("legal_entity", uid),
        name=entity.name,
        short_name=entity.short_name,
        country_code=entity.country_code,
        status=entity.status,
        version=entity.version,
    )


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
        .where(LegalEntity.archived_at.is_(None))  # type: ignore[attr-defined]
    )
    ids = _entity_scope_ids(scope)
    if ids is not None:
        if not ids:
            return []
        q = q.where(LegalEntity.id.in_(ids))
    rows = await session.execute(q)
    return [
        LegalEntityResponse(
            id=to_typed_id("legal_entity", r.id),
            name=r.name,
            short_name=r.short_name,
            country_code=r.country_code,
            status=r.status,
            version=r.version,
        )
        for r in rows.scalars()
    ]


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
    return LocationResponse(
        id=to_typed_id("location", uid),
        name=loc.name,
        type=loc.type,
        city=loc.city,
        state_code=loc.state_code,
        country_code=loc.country_code,
        timezone=loc.timezone,
        status=loc.status,
        version=loc.version,
        legal_entity_id=to_typed_id("legal_entity", le_uuid) if le_uuid else None,
    )


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
    if ids is None:
        rows = await session.execute(
            select(Location)
            .where(Location.tenant_id == tenant_id)
            .where(Location.archived_at.is_(None))  # type: ignore[attr-defined]
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
            await session.execute(select(Location).where(Location.id.in_(loc_ids)))
            if loc_ids
            else None
        )
    scalars = rows.scalars() if rows is not None else []
    return [
        LocationResponse(
            id=to_typed_id("location", r.id),
            name=r.name,
            type=r.type,
            city=r.city,
            state_code=r.state_code,
            country_code=r.country_code,
            timezone=r.timezone,
            status=r.status,
            version=r.version,
            legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id)
            if r.legal_entity_id
            else None,
        )
        for r in scalars
    ]


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
    loc_uuid: UUID | None = None
    if body.location_id:
        loc_uuid = to_uuid(body.location_id)

    unit = OrgUnit(
        tenant_id=tenant_id,
        id=uid,
        name=body.name,
        code=body.code,
        type=body.type,
        parent_id=parent_uuid,
        legal_entity_id=le_uuid,
        location_id=loc_uuid,
        effective_from=body.effective_from,
    )
    session.add(unit)
    await session.flush()
    return OrgUnitResponse(
        id=to_typed_id("org_unit", uid),
        name=unit.name,
        code=unit.code,
        type=unit.type,
        parent_id=to_typed_id("org_unit", parent_uuid) if parent_uuid else None,
        legal_entity_id=to_typed_id("legal_entity", le_uuid) if le_uuid else None,
        status=unit.status,
        effective_from=unit.effective_from,
        effective_to=unit.effective_to,
        version=unit.version,
    )


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
            .where(OrgUnit.archived_at.is_(None))  # type: ignore[attr-defined]
        )
        scalars = rows.scalars()
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
            (await session.execute(select(OrgUnit).where(OrgUnit.id.in_(unit_ids)))).scalars()
            if unit_ids
            else []
        )
    return [
        OrgUnitResponse(
            id=to_typed_id("org_unit", r.id),
            name=r.name,
            code=r.code,
            type=r.type,
            parent_id=to_typed_id("org_unit", r.parent_id) if r.parent_id else None,
            legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id)
            if r.legal_entity_id
            else None,
            status=r.status,
            effective_from=r.effective_from,
            effective_to=r.effective_to,
            version=r.version,
        )
        for r in scalars
    ]


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
    return JobResponse(
        id=to_typed_id("job", uid),
        title=job.title,
        code=job.code,
        function=job.function,
        status=job.status,
        version=job.version,
    )


@router.get("/jobs", response_model=list[JobResponse], summary="List jobs")
async def list_jobs(
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[JobResponse]:
    rows = await session.execute(
        select(Job).where(Job.tenant_id == tenant_id).where(Job.archived_at.is_(None))  # type: ignore[attr-defined]
    )
    return [
        JobResponse(
            id=to_typed_id("job", r.id),
            title=r.title,
            code=r.code,
            function=r.function,
            status=r.status,
            version=r.version,
        )
        for r in rows.scalars()
    ]


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
        .outerjoin(LegalEntity, LegalEntity.id == EmployeeIdScheme.legal_entity_id)
        .where(EmployeeIdScheme.tenant_id == tenant_id)
        .where(EmployeeIdScheme.archived_at.is_(None))  # type: ignore[attr-defined]
    )
    ids = _entity_scope_ids(scope)
    if ids is not None:
        if not ids:
            return []
        # A scoped caller sees their own companies' schemes, plus the
        # tenant-wide one (legal_entity_id IS NULL) if it exists — they're
        # affected by it even though they can't create it.
        q = q.where(
            (EmployeeIdScheme.legal_entity_id.in_(ids))
            | (EmployeeIdScheme.legal_entity_id.is_(None))
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
        .where(EmployeeIdScheme.archived_at.is_(None))  # type: ignore[attr-defined]
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
    for k, v in body.model_dump(exclude_unset=True).items():
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
        .outerjoin(LegalEntity, LegalEntity.id == EmployeeIdScheme.legal_entity_id)
        .where(EmployeeIdScheme.tenant_id == tenant_id)
        .where(EmployeeIdScheme.id == uid)
    )
    result = row.first()
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee ID scheme not found")
    return result

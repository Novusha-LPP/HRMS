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
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.org.models import Job, LegalEntity, Location, OrgUnit
from hrms.modules.org.schemas import (
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
        rows = await session.execute(select(Location).where(Location.id.in_(loc_ids))) if loc_ids else None
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
            legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id) if r.legal_entity_id else None,
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
        scalars = (await session.execute(select(OrgUnit).where(OrgUnit.id.in_(unit_ids)))).scalars() if unit_ids else []
    return [
        OrgUnitResponse(
            id=to_typed_id("org_unit", r.id),
            name=r.name,
            code=r.code,
            type=r.type,
            parent_id=to_typed_id("org_unit", r.parent_id) if r.parent_id else None,
            legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id) if r.legal_entity_id else None,
            status=r.status,
            effective_from=r.effective_from,
            effective_to=r.effective_to,
            version=r.version,
        )
        for r in scalars
    ]


# ─── Jobs (tenant-wide catalog — no per-company scoping) ──────────────────────

@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED,
             summary="Create a job", dependencies=[require_permission("org.write")])
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
        select(Job)
        .where(Job.tenant_id == tenant_id)
        .where(Job.archived_at.is_(None))  # type: ignore[attr-defined]
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

"""
Reports module.

GET  /v1/reports/meta/{module}   — available columns + filters for a module
GET  /v1/reports                 — list saved definitions (system + custom)
POST /v1/reports                 — save a custom report definition
GET  /v1/reports/{id}            — get a definition
POST /v1/reports/{id}/run        — execute and return rows
DELETE /v1/reports/{id}          — delete a custom report
"""

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authz import Scope, ScopeDep, require_global_permission, require_permission
from hrms.core.database import SessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.modules.reports.column_meta import (
    AVAILABLE_COLUMNS,
    AVAILABLE_FILTERS,
    DEFAULT_REPORTS,
)
from hrms.modules.reports.models import ReportDefinition, ReportModule

router = APIRouter(prefix="/v1/reports", tags=["Reports"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class ColumnSpec(BaseModel):
    field: str
    label: str
    visible: bool = True


class FilterSpec(BaseModel):
    field: str
    op: str
    value: object


class ReportDefCreate(BaseModel):
    name: str
    description: str = ""
    module: ReportModule
    columns: list[ColumnSpec]
    filters: list[FilterSpec] = []
    owner_type: str = "HR"


class ReportDefResponse(BaseModel):
    id: str
    name: str
    description: str
    module: ReportModule
    columns: list[dict]
    filters: list[dict]
    is_system: bool
    owner_type: str


class RunRequest(BaseModel):
    # Override filters at run time (e.g. set date range for this run)
    filters: list[FilterSpec] = []
    limit: int = 1000


class RunResponse(BaseModel):
    report_id: str
    name: str
    module: str
    columns: list[dict]  # visible columns in order
    rows: list[dict]
    total_rows: int
    generated_at: datetime


# ─── Column / filter metadata ─────────────────────────────────────────────────


@router.get("/meta/{module}", summary="Available columns and filters for a module")
async def report_meta(module: ReportModule) -> dict:
    return {
        "module": module,
        "columns": AVAILABLE_COLUMNS.get(module.value, []),
        "filters": AVAILABLE_FILTERS.get(module.value, []),
    }


# ─── CRUD ─────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[ReportDefResponse],
    summary="List report definitions",
    dependencies=[require_permission("reports.read")],
)
async def list_reports(
    tenant_id: TenantDep,
    session: SessionDep,
    owner_type: str | None = Query(default=None),
) -> list[ReportDefResponse]:
    # Seed defaults if none exist yet
    await _ensure_defaults(session, tenant_id)

    q = (
        select(ReportDefinition)
        .where(ReportDefinition.tenant_id == tenant_id)
        .where(ReportDefinition.archived_at.is_(None))  # type: ignore[attr-defined]
    )
    if owner_type:
        q = q.where(
            (ReportDefinition.owner_type == owner_type) | (ReportDefinition.owner_type == "ALL")
        )
    rows = await session.execute(q.order_by(ReportDefinition.is_system.desc()))  # type: ignore
    return [_def_response(r) for r in rows.scalars()]


@router.post(
    "",
    response_model=ReportDefResponse,
    status_code=201,
    dependencies=[require_global_permission("reports.write")],
)
async def create_report(
    body: ReportDefCreate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> ReportDefResponse:
    uid = uuid4()
    rd = ReportDefinition(
        tenant_id=tenant_id,
        id=uid,
        name=body.name,
        description=body.description,
        module=body.module,
        columns=json.dumps([c.model_dump() for c in body.columns]),
        filters=json.dumps([f.model_dump() for f in body.filters]),
        owner_type=body.owner_type,
        is_system=False,
    )
    session.add(rd)
    await session.flush()
    return _def_response(rd)


@router.get(
    "/{report_id}",
    response_model=ReportDefResponse,
    dependencies=[require_permission("reports.read")],
)
async def get_report(
    report_id: str, tenant_id: TenantDep, session: SessionDep
) -> ReportDefResponse:
    rd = await _fetch_def(session, tenant_id, report_id)
    return _def_response(rd)


@router.delete(
    "/{report_id}", status_code=204, dependencies=[require_global_permission("reports.write")]
)
async def delete_report(report_id: str, tenant_id: TenantDep, session: SessionDep) -> None:
    rd = await _fetch_def(session, tenant_id, report_id)
    if rd.is_system:
        raise HTTPException(status_code=403, detail="Cannot delete a system report")
    rd.archived_at = datetime.now(UTC)
    session.add(rd)


@router.post(
    "/{report_id}/run",
    response_model=RunResponse,
    summary="Execute a report and return rows",
    dependencies=[require_permission("reports.read")],
)
async def run_report(
    report_id: str,
    body: RunRequest,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> RunResponse:
    scope = scope.for_permission("reports.read")
    rd = await _fetch_def(session, tenant_id, report_id)
    saved_columns = json.loads(rd.columns)
    saved_filters = json.loads(rd.filters)

    # Merge run-time filter overrides
    run_filters = saved_filters.copy()
    for override in body.filters:
        # Replace matching field+op or append
        replaced = False
        for i, sf in enumerate(run_filters):
            if sf.get("field") == override.field and sf.get("op") == override.op:
                run_filters[i] = override.model_dump()
                replaced = True
                break
        if not replaced:
            run_filters.append(override.model_dump())

    rows = await _execute_report(
        session, tenant_id, rd.module, saved_columns, run_filters, body.limit, scope
    )
    visible = [c for c in saved_columns if c.get("visible", True)]

    return RunResponse(
        report_id=to_typed_id("report_definition", rd.id),
        name=rd.name,
        module=rd.module,
        columns=visible,
        rows=rows,
        total_rows=len(rows),
        generated_at=datetime.now(UTC),
    )


# ─── Query execution ──────────────────────────────────────────────────────────


async def _execute_report(
    session,
    tenant_id: UUID,
    module: str,
    columns: list[dict],
    filters: list[dict],
    limit: int,
    scope: Scope,
) -> list[dict]:
    """Build and run the SQL for each module type."""

    if module == "ATTENDANCE":
        return await _run_attendance(session, tenant_id, columns, filters, limit, scope)
    elif module == "EMPLOYEE":
        return await _run_employee(session, tenant_id, columns, filters, limit, scope)
    elif module == "ONBOARDING":
        return await _run_onboarding(session, tenant_id, columns, filters, limit, scope)
    elif module == "HEADCOUNT":
        return await _run_headcount(session, tenant_id, filters, limit, scope)
    elif module == "LEAVE":
        return await _run_leave(session, tenant_id, filters, limit, scope)
    return []


async def _run_attendance(session, tenant_id, columns, filters, limit, scope: Scope) -> list[dict]:
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params: dict = {"tid": str(tenant_id), "limit": limit, **entity_params}
    where = ["ad.tenant_id = CAST(:tid AS uuid)"]

    for i, f in enumerate(filters):
        key = f"f{i}"
        if f["field"] == "work_date" and f.get("value"):
            # asyncpg's date codec needs a native date, not the ISO string the
            # filter arrives as from the request body.
            try:
                value = date.fromisoformat(str(f["value"]))
            except ValueError:
                continue
            if f["op"] == "gte":
                where.append(f"ad.work_date >= CAST(:{key} AS date)")
                params[key] = value
            elif f["op"] == "lte":
                where.append(f"ad.work_date <= CAST(:{key} AS date)")
                params[key] = value
        elif f["field"] == "status" and f.get("value"):
            vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
            placeholders = ", ".join(f":{key}_{j}" for j in range(len(vals)))
            where.append(f"ad.status IN ({placeholders})")
            for j, v in enumerate(vals):
                params[f"{key}_{j}"] = v

    sql = f"""
        SELECT
            e.employee_number,
            p.legal_first_name || ' ' || p.legal_last_name  AS employee_name,
            ou.name                                           AS department,
            ad.work_date,
            ad.status,
            ad.first_punch_in,
            ad.last_punch_out,
            ad.effective_minutes,
            ad.late_by_minutes,
            ad.early_departure_minutes,
            l.name                                            AS location
        FROM attendance_days ad
        JOIN employments e   ON e.tenant_id = ad.tenant_id AND e.id = ad.employment_id
        JOIN persons p       ON p.tenant_id = e.tenant_id  AND p.id = e.person_id
        LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
            AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE) AND a.effective_from
            <= CURRENT_DATE
        LEFT JOIN org_units ou  ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
        LEFT JOIN locations l   ON l.tenant_id = a.tenant_id  AND l.id = a.location_id
        WHERE {" AND ".join(where)}
          {entity_clause}
        ORDER BY ad.work_date DESC, e.employee_number
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


async def _run_employee(session, tenant_id, columns, filters, limit, scope: Scope) -> list[dict]:
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params: dict = {"tid": str(tenant_id), "limit": limit, **entity_params}
    where = ["e.tenant_id = CAST(:tid AS uuid)", "e.archived_at IS NULL"]

    for i, f in enumerate(filters):
        key = f"f{i}"
        if f["field"] == "employment_state" and f.get("value"):
            vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
            placeholders = ", ".join(f":{key}_{j}" for j in range(len(vals)))
            where.append(f"e.employment_state IN ({placeholders})")
            for j, v in enumerate(vals):
                params[f"{key}_{j}"] = v

    sql = f"""
        SELECT
            e.employee_number,
            p.legal_first_name || ' ' || p.legal_last_name AS legal_name,
            e.hire_date,
            e.employment_state,
            ou.name     AS department,
            j.title     AS job_title,
            l.name      AS location,
            g.name      AS grade,
            e.service_stage,
            p.date_of_birth,
            p.gender
        FROM employments e
        JOIN persons p         ON p.tenant_id = e.tenant_id AND p.id = e.person_id
        LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
            AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE) AND a.effective_from
            <= CURRENT_DATE
        LEFT JOIN org_units ou  ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
        LEFT JOIN jobs j        ON j.tenant_id = a.tenant_id  AND j.id = a.job_id
        LEFT JOIN locations l   ON l.tenant_id = a.tenant_id  AND l.id = a.location_id
        LEFT JOIN grades g      ON g.tenant_id = a.tenant_id  AND g.id = a.grade_id
        WHERE {" AND ".join(where)}
          {entity_clause}
        ORDER BY e.employee_number
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


async def _run_onboarding(session, tenant_id, columns, filters, limit, scope: Scope) -> list[dict]:
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params: dict = {"tid": str(tenant_id), "limit": limit, **entity_params}
    where = ["oc.tenant_id = CAST(:tid AS uuid)"]

    for i, f in enumerate(filters):
        key = f"f{i}"
        if f["field"] == "case_status" and f.get("value"):
            val = f["value"]
            if isinstance(val, list):
                placeholders = ", ".join(f":{key}_{j}" for j in range(len(val)))
                where.append(f"oc.status IN ({placeholders})")
                for j, v in enumerate(val):
                    params[f"{key}_{j}"] = v
            else:
                where.append(f"oc.status = :{key}")
                params[key] = val

    sql = f"""
        SELECT
            e.employee_number,
            p.legal_first_name || ' ' || p.legal_last_name AS employee_name,
            oc.hire_date,
            oc.status                            AS case_status,
            COUNT(oi.id)                         AS total_items,
            COUNT(oi.id) FILTER (WHERE oi.status = 'COMPLETED') AS completed_items,
            COUNT(oi.id) FILTER (WHERE oi.status NOT IN ('COMPLETED','SKIPPED')
                AND oi.due_date < CURRENT_DATE)   AS overdue_items,
            oc.started_at,
            oc.completed_at
        FROM onboarding_cases oc
        JOIN employments e ON e.tenant_id = oc.tenant_id AND e.id = oc.employment_id
        JOIN persons p     ON p.tenant_id = e.tenant_id  AND p.id = e.person_id
        LEFT JOIN onboarding_items oi ON oi.tenant_id = oc.tenant_id AND oi.case_id = oc.id
        WHERE {" AND ".join(where)}
          {entity_clause}
        GROUP BY oc.id, e.employee_number, p.legal_first_name, p.legal_last_name,
                 oc.hire_date, oc.status, oc.started_at, oc.completed_at
        ORDER BY oc.started_at DESC
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


async def _run_leave(session, tenant_id, filters, limit, scope: Scope) -> list[dict]:
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params: dict = {"tid": str(tenant_id), "limit": limit, **entity_params}
    where = ["la.tenant_id = CAST(:tid AS uuid)", "la.archived_at IS NULL"]

    for i, f in enumerate(filters):
        key = f"f{i}"
        if f["field"] == "status" and f.get("value"):
            vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
            placeholders = ", ".join(f":{key}_{j}" for j in range(len(vals)))
            where.append(f"la.status IN ({placeholders})")
            for j, v in enumerate(vals):
                params[f"{key}_{j}"] = v
        elif f["field"] in ("from_date", "to_date") and f.get("value"):
            try:
                value = date.fromisoformat(str(f["value"]))
            except ValueError:
                continue
            col = f"la.{f['field']}"
            if f["op"] == "gte":
                where.append(f"{col} >= CAST(:{key} AS date)")
                params[key] = value
            elif f["op"] == "lte":
                where.append(f"{col} <= CAST(:{key} AS date)")
                params[key] = value
        elif f["field"] == "department" and f.get("value"):
            vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
            placeholders = ", ".join(f":{key}_{j}" for j in range(len(vals)))
            where.append(f"ou.name IN ({placeholders})")
            for j, v in enumerate(vals):
                params[f"{key}_{j}"] = v

    sql = f"""
        SELECT
            e.employee_number,
            p.legal_first_name || ' ' || p.legal_last_name AS employee_name,
            ou.name                                          AS department,
            lt.name                                          AS leave_type_name,
            la.from_date,
            la.to_date,
            la.days_requested,
            la.status,
            la.applied_at
        FROM leave_applications la
        JOIN employments e   ON e.tenant_id = la.tenant_id AND e.id = la.employment_id
        JOIN persons p       ON p.tenant_id = e.tenant_id  AND p.id = e.person_id
        JOIN leave_types lt  ON lt.tenant_id = la.tenant_id AND lt.id = la.leave_type_id
        LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
            AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE) AND a.effective_from
            <= CURRENT_DATE
        LEFT JOIN org_units ou  ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
        WHERE {" AND ".join(where)}
          {entity_clause}
        ORDER BY la.from_date DESC, e.employee_number
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


async def _run_headcount(session, tenant_id, filters, limit, scope: Scope) -> list[dict]:
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params: dict = {"tid": str(tenant_id), "limit": limit, **entity_params}
    sql = f"""
        SELECT
            ou.name                          AS department,
            l.name                           AS location,
            a.worker_type,
            COUNT(DISTINCT e.id)             AS headcount,
            COUNT(DISTINCT e.id) FILTER (WHERE e.employment_state = 'ACTIVE') AS active,
            COUNT(DISTINCT e.id) FILTER (WHERE e.employment_state = 'NOTICE') AS on_notice
        FROM employments e
        LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
            AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE) AND a.effective_from
            <= CURRENT_DATE
        LEFT JOIN org_units ou  ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
        LEFT JOIN locations l   ON l.tenant_id = a.tenant_id  AND l.id = a.location_id
        WHERE e.tenant_id = CAST(:tid AS uuid)
          AND e.employment_state NOT IN ('SEPARATED')
          AND e.archived_at IS NULL
          {entity_clause}
        GROUP BY ou.name, l.name, a.worker_type
        ORDER BY department, location
        LIMIT :limit
    """
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _fetch_def(session, tenant_id: UUID, report_id: str) -> ReportDefinition:
    r_uuid = to_uuid(report_id)
    row = await session.execute(
        select(ReportDefinition)
        .where(ReportDefinition.tenant_id == tenant_id)
        .where(ReportDefinition.id == r_uuid)
        .where(ReportDefinition.archived_at.is_(None))  # type: ignore[attr-defined]
    )
    rd = row.scalars().first()
    if not rd:
        raise HTTPException(status_code=404, detail="Report not found")
    return rd


async def _has_system_reports(session, tenant_id: UUID) -> bool:
    row = await session.execute(
        select(ReportDefinition.id)
        .where(ReportDefinition.tenant_id == tenant_id)
        .where(ReportDefinition.is_system == True)  # noqa: E712
        .limit(1)
    )
    return row.first() is not None


async def _ensure_defaults(session, tenant_id: UUID) -> None:
    if await _has_system_reports(session, tenant_id):
        return  # already seeded — the overwhelmingly common case, no lock taken
    # First use in this tenant. Two simultaneous first requests would each see "none" and
    # each insert the full set, leaving every system report duplicated — so serialize, then
    # look again: the loser of the race finds the winner's rows and returns.
    await lock_resource(session, tenant_id, "report-defaults")
    if await _has_system_reports(session, tenant_id):
        return

    for r in DEFAULT_REPORTS:
        cols = [{"field": f, "label": f, "visible": True} for f in r["columns"]]
        session.add(
            ReportDefinition(
                tenant_id=tenant_id,
                id=uuid4(),
                name=r["name"],
                description=r["description"],
                module=r["module"],
                columns=json.dumps(cols),
                filters=json.dumps(r["filters"]),
                is_system=True,
                owner_type=r["owner_type"],
            )
        )
    # The session doesn't autoflush (see core/database.py), so without this
    # the caller's very next SELECT wouldn't see these rows until the next request.
    await session.flush()


def _def_response(rd: ReportDefinition) -> ReportDefResponse:
    return ReportDefResponse(
        id=to_typed_id("report_definition", rd.id),
        name=rd.name,
        description=rd.description or "",
        module=rd.module,
        columns=json.loads(rd.columns),
        filters=json.loads(rd.filters),
        is_system=rd.is_system,
        owner_type=rd.owner_type,
    )

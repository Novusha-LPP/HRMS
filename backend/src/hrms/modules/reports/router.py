"""
Reports module.

GET  /v1/reports/meta/{module}   — available columns + filters for a module
GET  /v1/reports                 — list saved definitions (system + custom)
POST /v1/reports                 — save a custom report definition
GET  /v1/reports/{id}            — get a definition
POST /v1/reports/{id}/run        — execute and return rows
POST /v1/reports/{id}/export-attendance — export the attendance calendar as Excel
DELETE /v1/reports/{id}          — delete a custom report
"""

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import col, select
from starlette.concurrency import run_in_threadpool

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
    limit: int = Field(default=1000, ge=1, le=10000)


class RunResponse(BaseModel):
    report_id: str
    name: str
    module: str
    columns: list[dict]  # visible columns in order
    rows: list[dict]
    total_rows: int
    truncated: bool = False
    generated_at: datetime


class AttendanceExportRequest(BaseModel):
    filters: list[FilterSpec] = []


def _merged_run_filters(saved_filters: list[dict], runtime_filters: list[FilterSpec]) -> list[dict]:
    """Replace overridden field/operator groups, retaining repeated runtime constraints."""
    override_keys = {(f.field, f.op) for f in runtime_filters}
    return [f for f in saved_filters if (f.get("field"), f.get("op")) not in override_keys] + [
        f.model_dump() for f in runtime_filters
    ]


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
        .where(col(ReportDefinition.archived_at).is_(None))
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
    if body.module == "ATTENDANCE":
        _attendance_filters([f.model_dump() for f in body.filters])
        allowed = {c["field"] for c in AVAILABLE_COLUMNS["ATTENDANCE"]}
        if not body.columns or any(c.field not in allowed for c in body.columns):
            raise HTTPException(422, "Choose valid attendance columns")
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

    # Replace each overridden field/operator group once, preserving repeated
    # runtime constraints instead of overwriting an earlier override.
    run_filters = _merged_run_filters(saved_filters, body.filters)

    rows = await _execute_report(
        session, tenant_id, rd.module, saved_columns, run_filters, body.limit + 1, scope
    )
    visible = [c for c in saved_columns if c.get("visible", True)]

    return RunResponse(
        report_id=to_typed_id("report_definition", rd.id),
        name=rd.name,
        module=rd.module,
        columns=visible,
        rows=rows[: body.limit],
        total_rows=min(len(rows), body.limit),
        truncated=len(rows) > body.limit,
        generated_at=datetime.now(UTC),
    )


def _attendance_export_filters(filters: list[dict]) -> tuple[date, date, list[dict]]:
    """Require an explicit finite calendar and apply every supported population constraint."""
    from hrms.modules.reports.attendance_service import validate_period

    _attendance_filters(filters)
    lower, upper, population = [], [], []
    for spec in filters:
        field, op, value = spec["field"], spec["op"], spec["value"]
        if value is None or value == "":
            continue
        if field == "work_date":
            if op == "between":
                lower.append(date.fromisoformat(str(value[0])))
                upper.append(date.fromisoformat(str(value[1])))
            else:
                parsed = date.fromisoformat(str(value))
                if op in {"eq", "gte"}:
                    lower.append(parsed)
                if op in {"eq", "lte"}:
                    upper.append(parsed)
        elif field == "status":
            raise HTTPException(
                422, "Remove the status filter to export the full calendar register"
            )
        elif field in {"employment_id", "department", "location"}:
            population.append(spec)
        else:
            raise HTTPException(422, "Remove unsupported filters before exporting the register")
    if not lower or not upper:
        raise HTTPException(422, "Choose both start and end dates before exporting the register")
    first, last = max(lower), min(upper)
    validate_period(first, last)
    return first, last, population


@router.post(
    "/{report_id}/export-attendance",
    summary="Download the attendance and leave calendar as Excel",
    dependencies=[require_permission("reports.read")],
)
async def export_attendance_report(
    report_id: str,
    body: AttendanceExportRequest,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> Response:
    from hrms.modules.reports.attendance_service import build_attendance_summary
    from hrms.modules.reports.attendance_xlsx import MIME, attendance_workbook

    report = await _fetch_def(session, tenant_id, report_id)
    if report.module != "ATTENDANCE":
        raise HTTPException(422, "Choose an attendance report to export the attendance register")
    filters = _merged_run_filters(json.loads(report.filters), body.filters)
    first, last, population = _attendance_export_filters(filters)
    data = await build_attendance_summary(
        session, tenant_id, scope, first, last, population_filters=population
    )
    workbook = await run_in_threadpool(attendance_workbook, data.model_dump())
    filename = f"AttendanceReport_{first.isoformat()}_to_{last.isoformat()}.xlsx"
    return Response(
        content=workbook,
        media_type=MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
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


def _attendance_filters(filters: list[dict]) -> tuple[list[str], dict]:
    """Reject invalid constraints instead of silently returning a broader report."""
    clauses: list[str] = []
    params: dict = {}
    metadata = {f["field"]: f for f in AVAILABLE_FILTERS["ATTENDANCE"]}
    dates = []
    for i, spec in enumerate(filters):
        field, op, value = spec.get("field"), spec.get("op"), spec.get("value")
        meta = metadata.get(field)
        if not meta or op not in meta["ops"]:
            raise HTTPException(422, "Unsupported attendance filter")
        # Empty saved defaults are placeholders, not constraints.
        if value is None or value == "":
            continue
        key = f"f{i}"
        if field == "work_date":
            values = value if op == "between" else [value]
            try:
                if not isinstance(values, list) or len(values) != (2 if op == "between" else 1):
                    raise ValueError
                parsed = [date.fromisoformat(str(v)) for v in values]
                if op == "between" and parsed[0] > parsed[1]:
                    raise ValueError
            except (ValueError, TypeError):
                raise HTTPException(422, "Supply valid ISO dates in chronological order") from None
            if op == "between":
                clauses.append(f"ad.work_date BETWEEN :{key}_0 AND :{key}_1")
                params.update({f"{key}_{j}": d for j, d in enumerate(parsed)})
                dates.extend([("gte", parsed[0]), ("lte", parsed[1])])
            else:
                operator = {"eq": "=", "gte": ">=", "lte": "<="}[str(op)]
                clauses.append(f"ad.work_date {operator} :{key}")
                params[key] = parsed[0]
                dates.append((str(op), parsed[0]))
        elif field == "employment_id":
            if not isinstance(value, str) or not value.startswith("emp_"):
                raise HTTPException(422, "Supply a valid employee identifier")
            params[key] = str(to_uuid(value))
            clauses.append(f"e.id = CAST(:{key} AS uuid)")
        else:
            values = value if isinstance(value, list) else [value]
            if not values or (op == "eq" and len(values) != 1):
                raise HTTPException(422, "Supply a nonempty filter value")
            if any(not isinstance(v, str) or not v.strip() for v in values):
                raise HTTPException(422, "Supply nonempty text filter values")
            if field == "status" and any(v not in meta["options"] for v in values):
                raise HTTPException(422, "Unknown attendance status")
            col = {"status": "ad.status", "department": "ou.name", "location": "l.name"}[str(field)]
            placeholders = ", ".join(f":{key}_{j}" for j in range(len(values)))
            clauses.append(f"{col} IN ({placeholders})")
            params.update({f"{key}_{j}": v for j, v in enumerate(values)})
    lower = [d for op, d in dates if op in ("eq", "gte")]
    upper = [d for op, d in dates if op in ("eq", "lte")]
    if lower and upper and max(lower) > min(upper):
        raise HTTPException(422, "Attendance date range is reversed or contradictory")
    return clauses, params


async def _run_attendance(session, tenant_id, columns, filters, limit, scope: Scope) -> list[dict]:
    entity_clause, entity_params = scope.employment_filter_sql("e")
    params: dict = {"tid": str(tenant_id), "limit": limit, **entity_params}
    where = ["ad.tenant_id = CAST(:tid AS uuid)"]

    clauses, filter_params = _attendance_filters(filters)
    where.extend(clauses)
    params.update(filter_params)

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
        LEFT JOIN LATERAL (
            SELECT assignment.* FROM assignments assignment
            WHERE assignment.tenant_id = e.tenant_id AND assignment.employment_id = e.id
              AND assignment.effective_from <= ad.work_date
              AND (assignment.effective_to IS NULL OR assignment.effective_to > ad.work_date)
            ORDER BY assignment.effective_from DESC, assignment.recorded_at DESC, assignment.id
            LIMIT 1
        ) a ON TRUE
        LEFT JOIN org_units ou  ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
        LEFT JOIN locations l   ON l.tenant_id = a.tenant_id  AND l.id = a.location_id
        WHERE {" AND ".join(where)}
          {entity_clause}
        ORDER BY ad.work_date DESC, e.employee_number, e.id, ad.id
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
        .where(col(ReportDefinition.archived_at).is_(None))
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

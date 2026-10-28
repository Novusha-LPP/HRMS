"""
Reports on people leaving, rejoining and moving between companies
(docs/REJOIN_DEVELOPMENT_PLAN.md, R8).

  GET /v1/people/reports/rejoins                 who rejoined, after how long, and why
  GET /v1/people/reports/company-transfers       who moved between companies
  GET /v1/leave/reports/separation-settlements   what happened to leavers' unused leave

Each takes `from_date` / `to_date` (default: the last 90 days) and `format=json|csv`. Only people
the caller's scope covers appear. CSV cells that a spreadsheet could read as a formula are
prefixed so a name or reason typed by a user can never run as one.
"""

import csv
import io
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text

from hrms.core.authz import ScopeDep, require_permission
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.tenancy import TenantDep
from hrms.modules.time.snapshots import csv_cell

router = APIRouter(tags=["People"])

LIMIT = 5000
Format = Literal["json", "csv"]


class ReportTable(BaseModel):
    title: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


def _range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    end = to_date or business_today()
    return from_date or end - timedelta(days=90), end


def _respond(title: str, columns: list[str], rows: list[list[Any]], fmt: Format, slug: str):
    truncated = len(rows) > LIMIT
    rows = rows[:LIMIT]
    if fmt == "json":
        return ReportTable(
            title=title,
            columns=columns,
            rows=[[v.isoformat() if isinstance(v, date) else v for v in r] for r in rows],
            truncated=truncated,
        )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([csv_cell(v.isoformat() if isinstance(v, date) else v) for v in r])
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}-{business_today():%Y%m%d}.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/v1/people/reports/rejoins", dependencies=[require_permission("people.write")])
async def report_rejoins(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    start, end = _range(from_date, to_date)
    clause, params = scope.for_permission("people.write").employment_filter_sql("e")
    rows = (
        await session.execute(
            text(f"""
                SELECT e.employee_number, p.legal_first_name || ' ' || p.legal_last_name,
                       le.name, rr.break_start, rr.break_end,
                       rr.break_end - rr.break_start, rr.mode, rr.break_condoned, rr.reason
                FROM rejoin_records rr
                JOIN employments e ON e.tenant_id = rr.tenant_id AND e.id = rr.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                WHERE rr.tenant_id = CAST(:tid AS uuid)
                  AND rr.break_end BETWEEN :start AND :end
                  {clause}
                ORDER BY rr.break_end DESC, e.employee_number
                LIMIT {LIMIT + 1}
            """),
            {"tid": str(tenant_id), "start": start, "end": end, **params},
        )
    ).all()
    return _respond(
        "People who rejoined",
        [
            "Employee ID",
            "Name",
            "Company",
            "Left on",
            "Rejoined on",
            "Days away",
            "Earlier service",
            "Break accepted",
            "Reason",
        ],
        [
            [
                *r[:6],
                "Continued" if r[6] == "CONTINUE" else "Started fresh",
                "Yes" if r[7] else "No",
                r[8],
            ]
            for r in rows
        ],
        format,
        "rejoins",
    )


@router.get(
    "/v1/people/reports/company-transfers", dependencies=[require_permission("people.write")]
)
async def report_company_transfers(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    start, end = _range(from_date, to_date)
    clause, params = scope.for_permission("people.write").employment_filter_sql("e")
    rows = (
        await session.execute(
            text(f"""
                SELECT ct.effective_date, p.legal_first_name || ' ' || p.legal_last_name,
                       e.employee_number, fl.name, e2.employee_number, tl.name,
                       ct.leave_mode, ct.reason
                FROM company_transfers ct
                JOIN employments e ON e.tenant_id = ct.tenant_id AND e.id = ct.from_employment_id
                JOIN employments e2 ON e2.tenant_id = ct.tenant_id AND e2.id = ct.to_employment_id
                JOIN persons p ON p.tenant_id = ct.tenant_id AND p.id = ct.person_id
                JOIN legal_entities fl ON fl.tenant_id = e.tenant_id AND fl.id = e.legal_entity_id
                JOIN legal_entities tl ON tl.tenant_id = e2.tenant_id AND tl.id = e2.legal_entity_id
                WHERE ct.tenant_id = CAST(:tid AS uuid)
                  AND ct.effective_date BETWEEN :start AND :end
                  {clause}
                ORDER BY ct.effective_date DESC, e.employee_number
                LIMIT {LIMIT + 1}
            """),
            {"tid": str(tenant_id), "start": start, "end": end, **params},
        )
    ).all()
    return _respond(
        "People moved between companies",
        [
            "Moved on",
            "Name",
            "Old employee ID",
            "From company",
            "New employee ID",
            "To company",
            "Leave",
            "Reason",
        ],
        [[*r[:6], "Carried over" if r[6] == "CARRY" else "Settled", r[7]] for r in rows],
        format,
        "company-transfers",
    )


@router.get(
    "/v1/leave/reports/separation-settlements", dependencies=[require_permission("leave.read")]
)
async def report_leave_settlements(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    start, end = _range(from_date, to_date)
    clause, params = scope.for_permission("leave.read").employment_filter_sql("e")
    rows = (
        await session.execute(
            text(f"""
                SELECT s.settled_on, e.employee_number,
                       p.legal_first_name || ' ' || p.legal_last_name,
                       lt.name, s.days, s.encashed_days, s.lapsed_days,
                       s.days - s.encashed_days - s.lapsed_days, s.action, s.hold_expires_on,
                       s.resolution
                FROM leave_separation_settlements s
                JOIN employments e ON e.tenant_id = s.tenant_id AND e.id = s.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN leave_types lt ON lt.tenant_id = s.tenant_id AND lt.id = s.leave_type_id
                WHERE s.tenant_id = CAST(:tid AS uuid)
                  AND s.settled_on BETWEEN :start AND :end
                  {clause}
                ORDER BY s.settled_on DESC, e.employee_number, lt.name
                LIMIT {LIMIT + 1}
            """),
            {"tid": str(tenant_id), "start": start, "end": end, **params},
        )
    ).all()
    return _respond(
        "Unused leave settled for people who left",
        [
            "Left on",
            "Employee ID",
            "Name",
            "Leave type",
            "Unused days",
            "Paid out",
            "Lapsed",
            "Still held",
            "Rule",
            "Hold ends",
            "How the hold ended",
        ],
        [
            [
                r[0],
                r[1],
                r[2],
                r[3],
                float(r[4]),
                float(r[5]),
                float(r[6]),
                float(r[7]),
                r[8].title(),
                r[9],
                (r[10] or "").title(),
            ]
            for r in rows
        ],
        format,
        "leave-settlements",
    )

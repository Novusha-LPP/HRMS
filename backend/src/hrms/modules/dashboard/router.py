"""
Dashboard module — role-based aggregated data.

GET /v1/dashboard/employee   — employee's own view
GET /v1/dashboard/manager    — manager's team view
GET /v1/dashboard/hr         — HR admin view (scoped to the caller's companies)
GET /v1/dashboard/super-admin — super admin / platform view

Every endpoint here used to trust a client-supplied employment_id /
manager_employment_id query parameter as identity, and hr/super-admin
aggregated across the WHOLE tenant regardless of who was asking — any
authenticated user could read any other employee's attendance, or an HR
manager scoped to one company would see every sister company's headcount.
Now: the acting employee is always the caller's own unless explicitly
overridden AND authorized by their scope, and every aggregate query is
filtered to the legal entities / employments the caller's scope covers.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    ScopeDep,
    authorize_employment,
    require_permission,
    resolve_acting_employment_id,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.dashboard import widgets
from hrms.modules.dashboard.schemas import LayoutItem, LayoutResponse, LayoutUpdate, WidgetInfo
from hrms.modules.dashboard.widgets import SECTIONS
from hrms.modules.onboarding.models import CaseStatus, OnboardingCase, OnboardingItem
from hrms.modules.people.models import PersonnelAction, PersonnelActionStatus
from hrms.modules.time.models import AttendanceDay, Punch, PunchType
from hrms.modules.time.presence import classify, is_late, present_sql

router = APIRouter(prefix="/v1/dashboard", tags=["Dashboard"])


# ─── Employee dashboard ───────────────────────────────────────────────────────


@router.get("/employee", summary="Employee self-service dashboard")
async def employee_dashboard(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
) -> dict:
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    today = business_today()
    month_start = today.replace(day=1)

    ad_row = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.employment_id == emp_uuid)
        .where(AttendanceDay.work_date == today)
    )
    today_ad = ad_row.scalars().first()

    last_punch_row = await session.execute(
        select(Punch)
        .where(Punch.tenant_id == tenant_id)
        .where(Punch.employment_id == emp_uuid)
        .order_by(Punch.punched_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    last_punch = last_punch_row.scalars().first()

    month_rows = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.employment_id == emp_uuid)
        .where(AttendanceDay.work_date >= month_start)
        .where(AttendanceDay.work_date <= today)
    )
    month_days = list(month_rows.scalars())
    present = sum(1 for d in month_days if classify(d.status, d.first_punch_in) == "present")
    absent = sum(1 for d in month_days if classify(d.status, d.first_punch_in) == "absent")
    late = sum(1 for d in month_days if is_late(d.status, d.late_by_minutes))

    ob_row = await session.execute(
        select(OnboardingCase)
        .where(OnboardingCase.tenant_id == tenant_id)
        .where(OnboardingCase.employment_id == emp_uuid)
        .where(OnboardingCase.status == CaseStatus.IN_PROGRESS)
        .limit(1)
    )
    ob_case = ob_row.scalars().first()
    onboarding = None
    if ob_case:
        items_row = await session.execute(
            select(OnboardingItem)
            .where(OnboardingItem.tenant_id == tenant_id)
            .where(OnboardingItem.case_id == ob_case.id)
        )
        items = list(items_row.scalars())
        total = len(items)
        done = sum(1 for i in items if i.status == "COMPLETED")
        onboarding = {
            "case_id": str(ob_case.id),
            "total": total,
            "completed": done,
            "pct": round(done / total * 100) if total else 0,
        }

    is_punched_in = (
        last_punch is not None
        and last_punch.punch_type == PunchType.IN
        and last_punch.punched_at.date() == today
    )

    return {
        "role": "EMPLOYEE",
        "today": {
            "date": today.isoformat(),
            "is_punched_in": is_punched_in,
            "punch_in_time": today_ad.first_punch_in.isoformat()
            if today_ad and today_ad.first_punch_in
            else None,
            "effective_minutes": today_ad.effective_minutes if today_ad else 0,
            "status": today_ad.status if today_ad else "ABSENT",
        },
        "month_summary": {
            "month": month_start.strftime("%B %Y"),
            "present": present,
            "absent": absent,
            "late": late,
            "working_days": len(month_days),
        },
        "onboarding": onboarding,
    }


# ─── Manager dashboard ────────────────────────────────────────────────────────


@router.get("/manager", summary="Manager dashboard — team attendance and approvals")
async def manager_dashboard(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    manager_employment_id: str | None = Query(
        default=None, description="Defaults to your own employment"
    ),
) -> dict:
    mgr_uuid = resolve_acting_employment_id(principal, manager_employment_id)
    await authorize_employment(session, tenant_id, scope, mgr_uuid)

    today = business_today()

    team_rows = await session.execute(
        text("""
            SELECT e.id, p.legal_first_name || ' ' || p.legal_last_name AS name,
                   e.employee_number
            FROM assignment_managers am
            JOIN assignments a   ON a.tenant_id = am.tenant_id AND a.id = am.assignment_id
            JOIN employments e   ON e.tenant_id = a.tenant_id  AND e.id = a.employment_id
            JOIN persons p       ON p.tenant_id = e.tenant_id  AND p.id = e.person_id
            WHERE am.tenant_id = CAST(:tid AS uuid)
              AND am.manager_employment_id = CAST(:mgr AS uuid)
              AND am.manager_type = 'LINE'
              AND am.effective_to IS NULL
              AND e.employment_state NOT IN ('SEPARATED')
        """),
        {"tid": str(tenant_id), "mgr": str(mgr_uuid)},
    )
    team = [dict(r._mapping) for r in team_rows]
    team_ids = [r["id"] for r in team]

    attendance_summary = {"present": 0, "absent": 0, "on_leave": 0, "not_yet_in": 0}
    if team_ids:
        att_rows = await session.execute(
            text("""
                SELECT ad.employment_id, ad.status, ad.first_punch_in
                FROM attendance_days ad
                WHERE ad.tenant_id = CAST(:tid AS uuid)
                  AND ad.work_date = CAST(:today AS date)
                  AND ad.employment_id = ANY(CAST(:team_ids AS uuid[]))
            """),
            {"tid": str(tenant_id), "today": today, "team_ids": [str(i) for i in team_ids]},
        )
        att_map = {r._mapping["employment_id"]: r._mapping for r in att_rows}
        for tid_emp in team_ids:
            ad = att_map.get(tid_emp)
            if not ad:
                attendance_summary["absent"] += 1
            elif classify(ad["status"], ad["first_punch_in"]) == "present":
                attendance_summary["present"] += 1
            elif ad["status"] == "ON_LEAVE":
                attendance_summary["on_leave"] += 1
            elif not ad["first_punch_in"]:
                attendance_summary["not_yet_in"] += 1

    pending_pa = await session.execute(
        select(PersonnelAction)
        .where(PersonnelAction.tenant_id == tenant_id)
        .where(PersonnelAction.status == PersonnelActionStatus.PENDING_APPROVAL)
        .where(PersonnelAction.employment_id.in_(team_ids))  # type: ignore[attr-defined]
        .limit(10)
    )
    pending = list(pending_pa.scalars())
    names = {r["id"]: r["name"] for r in team}

    pending_requests: list[dict] = [
        {
            "kind": "PERSONNEL_ACTION",
            "id": to_typed_id("personnel_action", pa.id),
            "employment_id": to_typed_id("employment", pa.employment_id),
            "name": names.get(pa.employment_id, "—"),
            "detail": pa.type,
            "submitted_at": pa.effective_date.isoformat(),
            "link": "/employees",
        }
        for pa in pending
    ]
    if team_ids:
        pending_requests += [
            {
                "kind": "LEAVE",
                "id": to_typed_id("leave_application", r["id"]),
                "employment_id": to_typed_id("employment", r["employment_id"]),
                "name": r["name"],
                "detail": f"{r['leave_type_name']} · {r['days_requested']:g}d · {r['from_date']}"
                + (f" – {r['to_date']}" if r["to_date"] != r["from_date"] else ""),
                "submitted_at": r["applied_at"].isoformat(),
                "link": "/leave?tab=approvals",
            }
            for r in (
                await session.execute(
                    text("""
                SELECT la.id, la.employment_id, la.applied_at, la.from_date, la.to_date,
                       la.days_requested, lt.name AS leave_type_name,
                       p.legal_first_name || ' ' || p.legal_last_name AS name
                FROM leave_applications la
                JOIN leave_types lt ON lt.tenant_id = la.tenant_id AND lt.id = la.leave_type_id
                JOIN employments e ON e.tenant_id = la.tenant_id AND e.id = la.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                WHERE la.tenant_id = CAST(:tid AS uuid)
                  AND la.employment_id = ANY(CAST(:team_ids AS uuid[]))
                  AND (la.status LIKE 'PENDING%' OR la.status LIKE 'CANCEL_PENDING%')
                ORDER BY la.applied_at DESC LIMIT 10
            """),
                    {"tid": str(tenant_id), "team_ids": [str(i) for i in team_ids]},
                )
            )
            .mappings()
            .all()
        ]
        pending_requests += [
            {
                "kind": "CORRECTION",
                "id": to_typed_id("attendance_correction", r["id"]),
                "employment_id": to_typed_id("employment", r["employment_id"]),
                "name": r["name"],
                "detail": f"{r['correction_type']} · {r['work_date']}",
                "submitted_at": r["submitted_at"].isoformat(),
                "link": "/corrections?tab=approvals",
            }
            for r in (
                await session.execute(
                    text("""
                SELECT c.id, c.employment_id, c.submitted_at, c.work_date, c.correction_type,
                       p.legal_first_name || ' ' || p.legal_last_name AS name
                FROM attendance_correction_requests c
                JOIN employments e ON e.tenant_id = c.tenant_id AND e.id = c.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                WHERE c.tenant_id = CAST(:tid AS uuid)
                  AND c.employment_id = ANY(CAST(:team_ids AS uuid[]))
                  AND c.status LIKE 'PENDING%'
                ORDER BY c.submitted_at DESC LIMIT 10
            """),
                    {"tid": str(tenant_id), "team_ids": [str(i) for i in team_ids]},
                )
            )
            .mappings()
            .all()
        ]
    pending_requests.sort(key=lambda r: r["submitted_at"], reverse=True)

    return {
        "role": "MANAGER",
        "team_size": len(team),
        "today": {"date": today.isoformat(), **attendance_summary},
        "team": team,
        "pending_approvals": pending_requests[:10],
    }


# ─── HR dashboard ─────────────────────────────────────────────────────────────


# Today's assignment (one row per employment) and its department. The date test is
# the same everywhere an "as of today" assignment is needed — an open-ended
# assignment that starts in the future, or one that has ended, is not current.
_CURRENT_DEPARTMENT = """
    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
        AND a.effective_from <= CURRENT_DATE
        AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
    LEFT JOIN org_units assigned_unit
        ON assigned_unit.tenant_id = a.tenant_id AND assigned_unit.id = a.org_unit_id
    LEFT JOIN org_units ou ON ou.tenant_id = assigned_unit.tenant_id
        AND ou.id = CASE WHEN assigned_unit.type = 'TEAM'
            THEN assigned_unit.parent_id ELSE assigned_unit.id END
"""

_UPCOMING_DAYS = 45

# "Current employee" everywhere below means anyone not SEPARATED — probation, notice
# and on-hold staff included. (Filtering on ACTIVE alone drops every new hire: a
# hire starts in PROBATION until a CONFIRM action, so "recent joiners" would be empty.)


def _mmdd_window(today: date, days: int = _UPCOMING_DAYS) -> list[str]:
    """
    'MM-DD' for each of the next `days` days, so SQL can pick out just the people
    whose birthday/anniversary falls in the window instead of loading everyone.
    A 29 February date is celebrated on the 28th in non-leap years (see
    _next_occurrence), so it must be selectable whenever the 28th is.
    """
    window = {(today + timedelta(days=i)).strftime("%m-%d") for i in range(days + 1)}
    if "02-28" in window:
        window.add("02-29")
    return sorted(window)


def _next_occurrence(anchor: date, today: date) -> date:
    """The next date on or after `today` that falls on anchor's month and day."""

    def in_year(year: int) -> date:
        try:
            return anchor.replace(year=year)
        except ValueError:  # 29 February in a non-leap year
            return anchor.replace(year=year, day=28)

    upcoming = in_year(today.year)
    return upcoming if upcoming >= today else in_year(today.year + 1)


@router.get("/hr", summary="HR admin dashboard", dependencies=[require_permission("dashboard.hr")])
async def hr_dashboard(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    legal_entity_id: str | None = Query(
        default=None,
        description="Narrow every figure to one company the caller can already see "
        "(an extra filter on top of their scope, never a widening).",
    ),
    sections: str | None = Query(
        default=None,
        description="Comma-separated sections to compute (see dashboard/widgets.py SECTIONS). "
        "Omit for all of them. The web app asks only for what the caller's widgets show.",
    ),
) -> dict:
    """
    Every figure here is limited to the employees the caller's dashboard.hr grants
    cover (`emp_clause`, always against the alias `e`): an HR manager scoped to one
    company sees that company's headcount, KYC status, tenure and departments — not
    the group's. (The clause used to be built for the alias `employments` and reused
    in queries that alias the table `e`, which made every entity-scoped HR manager and
    accountant get a 500, and several aggregates skipped the clause altogether.)

    Each section runs only when asked for, and a query shared by several sections (KYC
    counts, the distributions) runs once per request.
    """
    scope = scope.for_permission("dashboard.hr")
    if sections is None:
        wanted = set(SECTIONS)
    else:
        wanted = {s.strip() for s in sections.split(",") if s.strip()}
        unknown = wanted - set(SECTIONS)
        if unknown:
            raise HTTPException(422, f"Unknown dashboard section(s): {', '.join(sorted(unknown))}")
    today = business_today()
    month_start = today.replace(day=1)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
    emp_clause, emp_params = scope.employment_filter_sql("e")
    focus = to_uuid(legal_entity_id) if legal_entity_id else None
    if focus is not None:
        # AND-ed onto the scope clause, so it can only ever narrow what the caller sees.
        emp_clause += " AND e.legal_entity_id = CAST(:focus_le AS uuid)"
        emp_params = {**emp_params, "focus_le": str(focus)}
    base = {"tid": str(tenant_id), **emp_params}

    async def rows(sql: str, **params):
        return (await session.execute(text(sql), {**base, **params})).mappings().all()

    async def one(sql: str, **params):
        return (await session.execute(text(sql), {**base, **params})).mappings().first()

    computed: dict = {}

    async def once(name, compute):
        if name not in computed:
            computed[name] = await compute()
        return computed[name]

    async def _emp_aggregates():
        return await one(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE e.archived_at IS NULL AND e.employment_state !=
                'SEPARATED') AS total,
                COUNT(*) FILTER (WHERE e.archived_at IS NULL AND e.employment_state =
                'ACTIVE') AS active,
                COUNT(*) FILTER (WHERE e.archived_at IS NULL AND e.employment_state =
                'PROBATION') AS probation,
                COUNT(*) FILTER (WHERE e.archived_at IS NULL AND e.employment_state =
                'PROBATION') AS on_probation,
                COUNT(*) FILTER (WHERE e.archived_at IS NULL AND e.employment_state =
                'NOTICE') AS on_notice,
                COUNT(*) FILTER (WHERE e.archived_at IS NULL AND e.employment_state =
                'ON_HOLD') AS on_hold,
                COUNT(*) FILTER (WHERE e.employment_state = 'SEPARATED') AS separated_count,
                COUNT(*) FILTER (WHERE e.hire_date >= CAST(:month_start AS date)) AS new_hires,
                COUNT(*) FILTER (WHERE e.archived_at IS NULL
                                   AND e.hire_date < CAST(:month_start AS date)
                                   AND (e.separation_date IS NULL OR e.separation_date >=
                                   CAST(:month_start AS date)))
                    AS headcount_last_month,
                COUNT(*) FILTER (WHERE e.hire_date >= CAST(:prev AS date)
                                   AND e.hire_date < CAST(:month_start AS date))
                    AS new_hires_last_month,
                COUNT(*) FILTER (WHERE e.separation_date IS NOT NULL
                                   AND e.separation_date <= CAST(:today AS date)
                                   AND e.separation_date >= CAST(:month_start AS date))
                    AS exits_this_month,
                COUNT(*) FILTER (WHERE e.separation_date IS NOT NULL
                                   AND e.separation_date <= CAST(:today AS date)
                                   AND e.separation_date >= CAST(:prev AS date)
                                   AND e.separation_date < CAST(:month_start AS date))
                    AS exits_last_month,
                COUNT(*) FILTER (WHERE e.separation_date IS NOT NULL
                                   AND e.separation_date <= CAST(:today AS date)
                                   AND e.separation_date > CAST(:today AS date) - 90)
                    AS exits_last_90_days,
                COUNT(*) FILTER (WHERE e.separation_date IS NOT NULL
                                   AND e.separation_date <= CAST(:today AS date)
                                   AND e.separation_date > CAST(:today AS date) - 365)
                    AS exits_last_12_months,
                AVG(CASE WHEN e.employment_state != 'SEPARATED' AND e.hire_date IS NOT NULL
                         THEN (CURRENT_DATE - e.hire_date) END) / 365.25 AS avg_years,
                COUNT(*) FILTER (WHERE e.employment_state != 'SEPARATED' AND e.hire_date IS NOT NULL
                                   AND CURRENT_DATE - e.hire_date >= 3652.5) AS over_10_years,
                COUNT(*) FILTER (WHERE e.employment_state != 'SEPARATED' AND e.hire_date IS NOT NULL
                                   AND CURRENT_DATE - e.hire_date >= 1826.25
                                   AND CURRENT_DATE - e.hire_date < 3652.5) AS tenure_5_to_10,
                COUNT(*) FILTER (WHERE e.employment_state != 'SEPARATED' AND e.hire_date IS NOT NULL
                                   AND CURRENT_DATE - e.hire_date < 1826.25) AS tenure_under_5
            FROM employments e
            WHERE e.tenant_id = CAST(:tid AS uuid)
              {emp_clause}
        """,
            month_start=month_start,
            prev=prev_month_start,
            today=today,
        )

    async def _action_counts():
        return await one(f"""
            SELECT
                (SELECT COUNT(*) FROM personnel_actions pa
                 JOIN employments e ON e.tenant_id = pa.tenant_id AND e.id = pa.employment_id
                 WHERE pa.tenant_id = CAST(:tid AS uuid) AND pa.status = 'PENDING_APPROVAL'
                 {emp_clause}) AS pending_pa,
                (SELECT COUNT(*) FROM personnel_actions pa
                 JOIN employments e ON e.tenant_id = pa.tenant_id AND e.id = pa.employment_id
                 WHERE pa.tenant_id = CAST(:tid AS uuid) AND pa.status = 'FAILED'
                 {emp_clause}) AS failed_pa,
                (SELECT COUNT(*) FROM leave_applications la
                 JOIN employments e ON e.tenant_id = la.tenant_id AND e.id = la.employment_id
                 WHERE la.tenant_id = CAST(:tid AS uuid)
                   AND (la.status LIKE 'PENDING%' OR la.status LIKE 'CANCEL_PENDING%')
                   {emp_clause}) AS pending_leave,
                (SELECT COUNT(*) FROM attendance_correction_requests c
                 JOIN employments e ON e.tenant_id = c.tenant_id AND e.id = c.employment_id
                 WHERE c.tenant_id = CAST(:tid AS uuid) AND c.status LIKE 'PENDING%'
                 {emp_clause}) AS pending_corrections,
                (SELECT COUNT(*) FROM onboarding_cases oc
                 JOIN employments e ON e.tenant_id = oc.tenant_id AND e.id = oc.employment_id
                 WHERE oc.tenant_id = CAST(:tid AS uuid) AND oc.status = 'IN_PROGRESS'
                 {emp_clause}) AS open_ob,
                (SELECT COUNT(*) FROM attendance_days ad
                 JOIN employments e ON e.tenant_id = ad.tenant_id AND e.id = ad.employment_id
                 WHERE ad.tenant_id = CAST(:tid AS uuid) AND ad.ot_status = 'PENDING'
                 {emp_clause}) AS pending_ot
        """)

    async def _headcount():
        aggs = await once("emp_aggs", _emp_aggregates)
        return {
            "headcount": {
                "total": aggs["total"],
                "active": aggs["active"],
                "probation": aggs["probation"],
                "on_notice": aggs["on_notice"],
            },
            "month": {"month": month_start.strftime("%B %Y"), "new_hires": aggs["new_hires"]},
        }

    async def _today():
        present = present_sql("ad")
        att = await one(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE {present}) AS present,
                COUNT(*) FILTER (WHERE NOT {present} AND ad.status = 'ABSENT') AS absent,
                COUNT(*) FILTER (WHERE NOT {present} AND ad.status = 'ON_LEAVE') AS on_leave,
                COUNT(*) FILTER (WHERE {present}
                                 AND (ad.status = 'LATE' OR ad.late_by_minutes > 0)) AS late
            FROM attendance_days ad
            JOIN employments e ON e.tenant_id = ad.tenant_id AND e.id = ad.employment_id
            WHERE ad.tenant_id = CAST(:tid AS uuid) AND ad.work_date = CAST(:today AS date)
              {emp_clause}
        """,
            today=today,
        )

        return {
            "date": today.isoformat(),
            "present": att["present"],
            "absent": att["absent"],
            "on_leave": att["on_leave"],
            "late": att["late"],
        }

    async def _kyc():
        kyc = await one(f"""
            SELECT COUNT(*) FILTER (WHERE k.status = 'VERIFIED') AS verified,
                   COUNT(*) FILTER (WHERE k.status = 'SUBMITTED') AS submitted,
                   COUNT(*) FILTER (WHERE k.status = 'ACTION_REQUIRED') AS action_required,
                   COUNT(*) FILTER (WHERE k.status = 'NOT_SUBMITTED') AS not_submitted
            FROM employee_kyc_records k
            JOIN employments e ON e.tenant_id = k.tenant_id AND e.id = k.employment_id
            WHERE k.tenant_id = CAST(:tid AS uuid)
              {emp_clause}
        """)

        return kyc

    async def _actions():
        counts = await once("action_counts", _action_counts)
        kyc = await once("kyc", _kyc)
        return {
            "pending_approvals": (
                counts["pending_pa"] + counts["pending_leave"] + counts["pending_corrections"]
            ),
            "pending_leave": counts["pending_leave"],
            "pending_corrections": counts["pending_corrections"],
            "pending_personnel_actions": counts["pending_pa"],
            "open_onboarding": counts["open_ob"],
            "pending_kyc": kyc["submitted"],
        }

    async def _pending_requests():
        # The actionable "who's waiting on you" queue — the most recent pending leave
        # requests and attendance corrections, by name, across everyone the caller's
        # scope covers. Personnel actions aren't included: they're reviewed from the
        # Employees page, which already surfaces them, not from this dashboard.
        pending_requests = sorted(
            [
                {
                    "kind": "LEAVE",
                    "id": to_typed_id("leave_application", r["id"]),
                    "employment_id": to_typed_id("employment", r["employment_id"]),
                    "name": r["name"],
                    "department": r["department"] or "General",
                    "company": r["company"],
                    "detail": (
                        f"{r['leave_type_name']} · {r['days_requested']:g}d · {r['from_date']}"
                        + (f" – {r['to_date']}" if r["to_date"] != r["from_date"] else "")
                    ),
                    "is_cancellation": r["status"].startswith("CANCEL"),
                    "submitted_at": r["applied_at"].isoformat(),
                    "link": "/leave?tab=approvals",
                }
                for r in await rows(f"""
                    SELECT la.id, la.employment_id, la.applied_at, la.from_date, la.to_date,
                           la.days_requested, la.status, lt.name AS leave_type_name,
                           p.legal_first_name || ' ' || p.legal_last_name AS name,
                           ou.name AS department, le.name AS company
                    FROM leave_applications la
                    JOIN leave_types lt ON lt.tenant_id = la.tenant_id AND lt.id = la.leave_type_id
                    JOIN employments e ON e.tenant_id = la.tenant_id AND e.id = la.employment_id
                    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                    JOIN legal_entities le
                      ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                    {_CURRENT_DEPARTMENT}
                    WHERE la.tenant_id = CAST(:tid AS uuid)
                      AND (la.status LIKE 'PENDING%' OR la.status LIKE 'CANCEL_PENDING%')
                      {emp_clause}
                    ORDER BY la.applied_at DESC LIMIT 8
                """)
            ]
            + [
                {
                    "kind": "CORRECTION",
                    "id": to_typed_id("attendance_correction", r["id"]),
                    "employment_id": to_typed_id("employment", r["employment_id"]),
                    "name": r["name"],
                    "department": r["department"] or "General",
                    "company": r["company"],
                    "detail": f"{r['correction_type']} · {r['work_date']}",
                    "is_cancellation": False,
                    "submitted_at": r["submitted_at"].isoformat(),
                    "link": "/corrections?tab=approvals",
                }
                for r in await rows(f"""
                    SELECT c.id, c.employment_id, c.submitted_at, c.work_date, c.correction_type,
                           p.legal_first_name || ' ' || p.legal_last_name AS name,
                           ou.name AS department, le.name AS company
                    FROM attendance_correction_requests c
                    JOIN employments e ON e.tenant_id = c.tenant_id AND e.id = c.employment_id
                    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                    JOIN legal_entities le
                      ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                    {_CURRENT_DEPARTMENT}
                    WHERE c.tenant_id = CAST(:tid AS uuid) AND c.status LIKE 'PENDING%'
                      {emp_clause}
                    ORDER BY c.submitted_at DESC LIMIT 8
                """)
            ],
            key=lambda r: r["submitted_at"],
            reverse=True,
        )[:8]

        return pending_requests

    async def _birthdays():
        # People with a birthday / work anniversary in the next 45 days.
        window = _mmdd_window(today)
        upcoming_birthdays = []
        for r in await rows(
            f"""
            SELECT p.legal_first_name || ' ' || p.legal_last_name AS name, e.employee_number,
                   p.date_of_birth, ou.name AS department, le.name AS company
            FROM employments e
            JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
            {_CURRENT_DEPARTMENT}
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state != 'SEPARATED'
              AND p.date_of_birth IS NOT NULL
              AND to_char(p.date_of_birth, 'MM-DD') = ANY(CAST(:window AS text[]))
              {emp_clause}
        """,
            window=window,
        ):
            next_birthday = _next_occurrence(r["date_of_birth"], today)
            upcoming_birthdays.append(
                {
                    "name": r["name"],
                    "employee_number": r["employee_number"],
                    "department": r["department"] or "General",
                    "company": r["company"],
                    "date": next_birthday.isoformat(),
                    "days_until": (next_birthday - today).days,
                }
            )
        upcoming_birthdays = sorted(upcoming_birthdays, key=lambda x: x["days_until"])[:6]

        return upcoming_birthdays

    async def _anniversaries():
        window = _mmdd_window(today)
        upcoming_anniversaries = []
        for r in await rows(
            f"""
            SELECT p.legal_first_name || ' ' || p.legal_last_name AS name, e.employee_number,
                   e.hire_date, ou.name AS department, le.name AS company
            FROM employments e
            JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
            {_CURRENT_DEPARTMENT}
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state != 'SEPARATED'
              AND e.hire_date IS NOT NULL
              AND to_char(e.hire_date, 'MM-DD') = ANY(CAST(:window AS text[]))
              {emp_clause}
        """,
            window=window,
        ):
            anniversary = _next_occurrence(r["hire_date"], today)
            years = anniversary.year - r["hire_date"].year
            if years > 0:
                upcoming_anniversaries.append(
                    {
                        "name": r["name"],
                        "employee_number": r["employee_number"],
                        "department": r["department"] or "General",
                        "company": r["company"],
                        "date": anniversary.isoformat(),
                        "days_until": (anniversary - today).days,
                        "years": years,
                    }
                )
        upcoming_anniversaries = sorted(upcoming_anniversaries, key=lambda x: x["days_until"])[:6]

        return upcoming_anniversaries

    async def _departments():
        department_distribution = [
            {"department": r["department"], "count": r["count"]}
            for r in await rows(f"""
                SELECT COALESCE(ou.name, 'Unassigned') AS department, COUNT(e.id) AS count
                FROM employments e
                {_CURRENT_DEPARTMENT}
                WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state != 'SEPARATED'
                  {emp_clause}
                GROUP BY ou.name
                ORDER BY count DESC
                LIMIT 6
            """)
        ]

        return department_distribution

    async def _entities():
        entity_distribution = [
            {"company": r["company"], "short_name": r["short_name"], "count": r["count"]}
            for r in await rows(f"""
                SELECT le.name AS company, le.short_name, COUNT(e.id) AS count
                FROM legal_entities le
                JOIN employments e ON e.tenant_id = le.tenant_id AND e.legal_entity_id = le.id
                     AND e.employment_state != 'SEPARATED' AND e.archived_at IS NULL
                WHERE le.tenant_id = CAST(:tid AS uuid)
                  {emp_clause}
                GROUP BY le.id, le.name, le.short_name
                ORDER BY count DESC
            """)
        ]

        return entity_distribution

    async def _recent_joiners():
        recent_joiners = [
            {
                "name": r["name"],
                "employee_number": r["employee_number"],
                "hire_date": r["hire_date"].isoformat() if r["hire_date"] else None,
                "company": r["company"],
                "department": r["department"] or "General",
                "designation": r["designation"],
            }
            for r in await rows(f"""
                SELECT p.legal_first_name || ' ' || p.legal_last_name AS name, e.employee_number,
                       e.hire_date, le.name AS company, ou.name AS department,
                       j.title AS designation
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                {_CURRENT_DEPARTMENT}
                LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
                WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state != 'SEPARATED'
                  AND e.archived_at IS NULL
                  {emp_clause}
                ORDER BY e.hire_date DESC NULLS LAST
                LIMIT 5
            """)
        ]

        return recent_joiners

    async def _tenure_row():
        aggs = await once("emp_aggs", _emp_aggregates)
        return {
            "avg_years": aggs["avg_years"],
            "over_10_years": aggs["over_10_years"],
            "tenure_5_to_10": aggs["tenure_5_to_10"],
            "tenure_under_5": aggs["tenure_under_5"],
        }

    async def _tenure():
        tenure = await once("tenure_row", _tenure_row)
        return {
            "avg_years": round(float(tenure["avg_years"]), 1) if tenure["avg_years"] else 0,
            "over_10_years": tenure["over_10_years"],
            "5_to_10_years": tenure["tenure_5_to_10"],
            "under_5_years": tenure["tenure_under_5"],
        }

    async def _kyc_summary():
        kyc = await once("kyc", _kyc)
        total = sum(
            (kyc[k] or 0) for k in ("verified", "submitted", "action_required", "not_submitted")
        )
        return {
            "verified": kyc["verified"],
            "submitted": kyc["submitted"],
            "action_required": kyc["action_required"],
            "not_submitted": kyc["not_submitted"],
            "rate_pct": round((kyc["verified"] or 0) / max(1, total) * 100, 1),
        }

    async def _org_summary():
        # Locations: every one for a group-wide caller; for a scoped caller, the locations
        # their own people are currently assigned to.
        if scope.is_all:
            location_count = (
                await one(
                    """
                SELECT COUNT(*) AS n FROM locations
                WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
                  AND (CAST(:focus_le AS uuid) IS NULL
                       OR legal_entity_id = CAST(:focus_le AS uuid))
            """,
                    focus_le=str(focus) if focus else None,
                )
            )["n"]
        else:
            location_count = (
                await one(f"""
                SELECT COUNT(DISTINCT a.location_id) AS n
                FROM employments e
                JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
                    AND a.effective_from <= CURRENT_DATE
                    AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
                WHERE e.tenant_id = CAST(:tid AS uuid)
                  {emp_clause}
            """)
            )["n"]

        separated_count = (await once("emp_aggs", _emp_aggregates))["separated_count"]

        entity_distribution = await once("entity_distribution", _entities)
        department_distribution = await once("department_distribution", _departments)
        tenure = await once("tenure", _tenure)
        return {
            "total_entities": len(entity_distribution),
            "total_departments": len(department_distribution),
            "total_locations": location_count,
            "separated_count": separated_count,
            "avg_tenure_years": tenure["avg_years"],
            "tenure_brackets": {
                "over_10_years": tenure["over_10_years"],
                "5_to_10_years": tenure["5_to_10_years"],
                "under_5_years": tenure["under_5_years"],
            },
            "kyc_compliance": await once("kyc_summary", _kyc_summary),
        }

    async def _exit_counts():
        aggs = await once("emp_aggs", _emp_aggregates)
        return {
            "exits_this_month": aggs["exits_this_month"],
            "exits_last_month": aggs["exits_last_month"],
            "exits_last_90_days": aggs["exits_last_90_days"],
            "exits_last_12_months": aggs["exits_last_12_months"],
        }

    async def _trends():
        """Last month's figures, so KPI cards can say "vs last month"."""
        aggs = await once("emp_aggs", _emp_aggregates)
        return {
            "headcount_last_month": aggs["headcount_last_month"],
            "new_hires_last_month": aggs["new_hires_last_month"],
            **(await once("exit_counts", _exit_counts)),
        }

    async def _exits():
        counts = await once("exit_counts", _exit_counts)
        headcount = (await once("headcount", _headcount))["headcount"]
        current = headcount["total"] or 0
        return {
            **counts,
            "on_notice": headcount["on_notice"],
            # Separations in the last 12 months as a share of today's headcount.
            "attrition_12m_pct": round(counts["exits_last_12_months"] / max(1, current) * 100, 1),
        }

    async def _attendance_30d():
        """Average daily presence over the last 30 days that have attendance (today excluded)."""
        present = present_sql("ad")
        start = today - timedelta(days=60)
        mid = today - timedelta(days=30)
        row = await one(
            f"""
            SELECT
                AVG(day.present) FILTER (WHERE day.work_date >= CAST(:mid AS date))::float AS
                now_avg,
                COUNT(*) FILTER (WHERE day.work_date >= CAST(:mid AS date)) AS days,
                AVG(day.present) FILTER (WHERE day.work_date < CAST(:mid AS date))::float AS
                prev_avg
            FROM (
                SELECT ad.work_date, COUNT(*) FILTER (WHERE {present}) AS present
                FROM attendance_days ad
                JOIN employments e ON e.tenant_id = ad.tenant_id AND e.id = ad.employment_id
                WHERE ad.tenant_id = CAST(:tid AS uuid)
                  AND ad.work_date >= CAST(:start AS date) AND ad.work_date < CAST(:today AS date)
                  {emp_clause}
                GROUP BY ad.work_date
            ) day
        """,
            start=start,
            mid=mid,
            today=today,
        )
        now_avg, days, prev_avg = row["now_avg"], row["days"], row["prev_avg"]

        current = (await once("headcount", _headcount))["headcount"]["total"] or 0

        def pct(avg):
            return round(avg / current * 100, 1) if avg is not None and current else None

        return {"avg_present_pct": pct(now_avg), "previous_pct": pct(prev_avg), "days": days}

    async def _vacancies():
        """Open seats in active positions (positions with a headcount limit)."""
        if scope.is_all:
            position_scope, params = "", {}
        elif scope.legal_entity_ids:
            position_scope = "AND ou.legal_entity_id = ANY(CAST(:pos_entities AS uuid[]))"
            params = {"pos_entities": [str(i) for i in scope.legal_entity_ids]}
        elif scope.org_unit_ids:
            position_scope = "AND p.org_unit_id = ANY(CAST(:pos_units AS uuid[]))"
            params = {"pos_units": [str(i) for i in scope.org_unit_ids]}
        else:
            position_scope, params = "AND FALSE", {}
        if focus is not None:  # narrows the scope above, never replaces it
            position_scope += " AND ou.legal_entity_id = CAST(:focus_le AS uuid)"
        row = await one(
            f"""
            SELECT COUNT(*) AS positions,
                   COALESCE(SUM(p.max_headcount), 0)::int AS capacity,
                   COALESCE(SUM(LEAST(filled.n, p.max_headcount)), 0)::int AS filled
            FROM positions p
            JOIN org_units ou ON ou.tenant_id = p.tenant_id AND ou.id = p.org_unit_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS n FROM assignments a
                JOIN employments e ON e.tenant_id = a.tenant_id AND e.id = a.employment_id
                WHERE a.tenant_id = p.tenant_id AND a.position_id = p.id
                  AND a.effective_from <= CURRENT_DATE
                  AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
                  AND e.employment_state != 'SEPARATED'
            ) filled ON true
            WHERE p.tenant_id = CAST(:tid AS uuid) AND p.archived_at IS NULL
              AND p.status = 'ACTIVE' AND p.max_headcount IS NOT NULL
              AND p.effective_from <= CURRENT_DATE
              AND (p.effective_to IS NULL OR p.effective_to > CURRENT_DATE)
              {position_scope}
        """,
            **params,
        )
        return {
            "positions": row["positions"],
            "capacity": row["capacity"],
            "filled": row["filled"],
            "vacancies": row["capacity"] - row["filled"],
        }

    async def _statutory():
        """Statutory IDs not on file for current employees, and passports expiring soon."""
        row = await one(
            f"""
            SELECT COUNT(*) AS employees,
                   COUNT(*) FILTER (WHERE k.id IS NULL) AS no_kyc_record,
                   COUNT(*) FILTER (WHERE COALESCE(k.uan_number, '') = '') AS missing_uan,
                   COUNT(*) FILTER (WHERE COALESCE(k.pf_number, '') = '') AS missing_pf,
                   COUNT(*) FILTER (WHERE COALESCE(k.esi_number, '') = '') AS missing_esi,
                   COUNT(*) FILTER (WHERE k.passport_expiry IS NOT NULL
                                      AND k.passport_expiry < CAST(:today AS date) + 90)
                       AS passports_expiring
            FROM employments e
            LEFT JOIN employee_kyc_records k
                   ON k.tenant_id = e.tenant_id AND k.employment_id = e.id
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.archived_at IS NULL
              AND e.employment_state != 'SEPARATED'
              {emp_clause}
        """,
            today=today,
        )
        return dict(row)

    async def _worker_types():
        return [
            {"worker_type": r["worker_type"], "count": r["count"]}
            for r in await rows(f"""
                SELECT COALESCE(a.worker_type, 'UNASSIGNED') AS worker_type, COUNT(*) AS count
                FROM employments e
                {_CURRENT_DEPARTMENT}
                WHERE e.tenant_id = CAST(:tid AS uuid) AND e.archived_at IS NULL
                  AND e.employment_state != 'SEPARATED'
                  {emp_clause}
                GROUP BY 1 ORDER BY count DESC
            """)
        ]

    async def _leave_by_department():
        """Approved leave days starting in the last 90 days, per department, and per head."""
        return [
            {
                "department": r["department"],
                "days": float(r["days"]),
                "headcount": r["headcount"],
                "days_per_person": round(float(r["days"]) / max(1, r["headcount"]), 1),
            }
            for r in await rows(
                f"""
                SELECT COALESCE(ou.name, 'Unassigned') AS department,
                       COUNT(DISTINCT e.id) AS headcount,
                       COALESCE(SUM(la.days_requested) FILTER (
                           WHERE la.status = 'APPROVED'
                             AND la.from_date > CAST(:today AS date) - 90
                       ), 0) AS days
                FROM employments e
                {_CURRENT_DEPARTMENT}
                LEFT JOIN leave_applications la
                       ON la.tenant_id = e.tenant_id AND la.employment_id = e.id
                      AND la.archived_at IS NULL
                WHERE e.tenant_id = CAST(:tid AS uuid) AND e.archived_at IS NULL
                  AND e.employment_state != 'SEPARATED'
                  {emp_clause}
                GROUP BY 1
                HAVING COALESCE(SUM(la.days_requested) FILTER (
                           WHERE la.status = 'APPROVED'
                             AND la.from_date > CAST(:today AS date) - 90
                       ), 0) > 0
                ORDER BY days DESC
                LIMIT 8
            """,
                today=today,
            )
        ]

    async def _lifecycle():
        aggs = await once("emp_aggs", _emp_aggregates)
        row = {
            "on_probation": aggs["on_probation"],
            "on_notice": aggs["on_notice"],
            "on_hold": aggs["on_hold"],
        }
        moved = {
            r["type"]: r["n"]
            for r in await rows(
                f"""
                SELECT pa.type, COUNT(*) AS n FROM personnel_actions pa
                JOIN employments e ON e.tenant_id = pa.tenant_id AND e.id = pa.employment_id
                WHERE pa.tenant_id = CAST(:tid AS uuid) AND pa.status = 'APPLIED'
                  AND pa.type IN ('CONFIRM', 'PROMOTION', 'TRANSFER')
                  AND pa.effective_date >= CAST(:month_start AS date)
                  {emp_clause}
                GROUP BY pa.type
            """,
                month_start=month_start,
            )
        }
        longest = [
            {
                "name": r["name"],
                "department": r["department"] or "General",
                "company": r["company"],
                "hire_date": r["hire_date"].isoformat() if r["hire_date"] else None,
                "months": r["months"],
            }
            for r in await rows(
                f"""
                SELECT p.legal_first_name || ' ' || p.legal_last_name AS name, e.hire_date,
                       ou.name AS department, le.name AS company,
                       (EXTRACT(YEAR FROM age(CAST(:today AS date), e.hire_date)) * 12
                        + EXTRACT(MONTH FROM age(CAST(:today AS date), e.hire_date)))::int AS months
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN legal_entities le
                  ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                {_CURRENT_DEPARTMENT}
                WHERE e.tenant_id = CAST(:tid AS uuid) AND e.archived_at IS NULL
                  AND e.employment_state = 'PROBATION' AND e.hire_date IS NOT NULL
                  {emp_clause}
                ORDER BY e.hire_date ASC
                LIMIT 5
            """,
                today=today,
            )
        ]
        return {
            **dict(row),
            "confirmed_this_month": moved.get("CONFIRM", 0),
            "promoted_this_month": moved.get("PROMOTION", 0),
            "transferred_this_month": moved.get("TRANSFER", 0),
            "longest_on_probation": longest,
        }

    async def _highlights_today():
        today_mmdd = today.strftime("%m-%d")

        current = "e.employment_state != 'SEPARATED'"
        company_clause = ""
        company_params = {}
        if not scope.is_all:
            company_clause = " AND le.id = ANY(CAST(:celebration_entities AS uuid[]))"
            company_params["celebration_entities"] = [str(i) for i in scope.legal_entity_ids]
        if focus is not None:
            company_clause += " AND le.id = CAST(:focus_le AS uuid)"
        company_anniversaries = [
            {"name": r["name"], "company": r["name"], "department": "Company", "years": r["years"]}
            for r in await rows(
                f"""
                SELECT le.name,
                       EXTRACT(YEAR FROM
                           age(CAST(:today AS date), le.establishment_date))::int AS years
                FROM legal_entities le
                WHERE le.tenant_id = CAST(:tid AS uuid) AND le.archived_at IS NULL
                  AND le.status = 'ACTIVE' AND le.establishment_date < CAST(:today AS date)
                  AND to_char(le.establishment_date, 'MM-DD') = :mmdd
                  {company_clause}
                ORDER BY le.name
                """,
                today=today, mmdd=today_mmdd, **company_params,
            )
        ]

        people_rows = await rows(
            f"""
            SELECT p.legal_first_name || ' ' || p.legal_last_name AS name,
                   ou.name AS department, le.name AS company,
                   EXTRACT(YEAR FROM age(CAST(:today AS date), e.hire_date))::int AS years,
                   (e.hire_date = CAST(:today AS date)) AS is_joining,
                   (e.separation_date = CAST(:today AS date)) AS is_exiting,
                   ({current} AND to_char(p.date_of_birth, 'MM-DD') = :mmdd) AS is_birthday,
                   ({current} AND e.hire_date < CAST(:today AS date) AND to_char(e.hire_date,
                   'MM-DD') = :mmdd) AS is_anniversary
            FROM employments e
            JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            JOIN legal_entities le
              ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
            {_CURRENT_DEPARTMENT}
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.archived_at IS NULL
              AND (
                   e.hire_date = CAST(:today AS date)
                OR e.separation_date = CAST(:today AS date)
                OR ({current} AND to_char(p.date_of_birth, 'MM-DD') = :mmdd)
                OR ({current} AND e.hire_date < CAST(:today AS date) AND to_char(e.hire_date,
                'MM-DD') = :mmdd)
              )
              {emp_clause}
            ORDER BY name
        """,
            today=today,
            mmdd=today_mmdd,
        )

        joining: list[dict[str, Any]] = []
        exiting: list[dict[str, Any]] = []
        birthdays: list[dict[str, Any]] = []
        anniversaries: list[dict[str, Any]] = []
        for r in people_rows:
            item = {
                "name": r["name"],
                "department": r["department"] or "General",
                "company": r["company"],
                "years": r["years"],
            }
            if r["is_joining"] and len(joining) < 20:
                joining.append(item)
            if r["is_exiting"] and len(exiting) < 20:
                exiting.append(item)
            if r["is_birthday"] and len(birthdays) < 20:
                birthdays.append(item)
            if r["is_anniversary"] and len(anniversaries) < 20:
                anniversaries.append(item)

        return {
            "company_anniversaries": company_anniversaries,
            "joining": joining,
            "exiting": exiting,
            "birthdays": birthdays,
            "anniversaries": anniversaries,
        }

    async def _scheduled_changes():
        """Personnel actions scheduled to take effect in the next 30 days."""
        return [
            {
                "type": r["type"],
                "effective_date": r["effective_date"].isoformat(),
                "days_until": (r["effective_date"] - today).days,
                "name": r["name"],
                "department": r["department"] or "General",
                "company": r["company"],
            }
            for r in await rows(
                f"""
                SELECT pa.type, pa.effective_date,
                       p.legal_first_name || ' ' || p.legal_last_name AS name,
                       ou.name AS department, le.name AS company
                FROM personnel_actions pa
                JOIN employments e ON e.tenant_id = pa.tenant_id AND e.id = pa.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN legal_entities le
                  ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                {_CURRENT_DEPARTMENT}
                WHERE pa.tenant_id = CAST(:tid AS uuid) AND pa.status = 'SCHEDULED'
                  AND pa.effective_date <= CAST(:today AS date) + 30
                  {emp_clause}
                ORDER BY pa.effective_date, name
                LIMIT 10
            """,
                today=today,
            )
        ]

    async def _action_centre():
        """Everything waiting on HR, as counts with where to deal with each."""
        actions = await once("actions", _actions)
        counts = await once("action_counts", _action_counts)
        statutory = await once("statutory", _statutory)
        overtime = counts["pending_ot"]
        failed = counts["failed_pa"]
        missing_statutory = max(
            statutory["missing_uan"], statutory["missing_pf"], statutory["missing_esi"]
        )
        items = [
            ("leave_approvals", "Leave approvals", actions["pending_leave"],
             "/leave?tab=approvals"),
            ("corrections", "Attendance corrections", actions["pending_corrections"],
             "/corrections?tab=approvals"),
            ("overtime", "Overtime to review", overtime, "/attendance"),
            ("personnel_actions", "Personnel actions to approve",
             actions["pending_personnel_actions"], "/employees"),
            ("failed_actions", "Scheduled changes that failed", failed, "/employees"),
            ("kyc", "KYC to verify", actions["pending_kyc"], "/employees"),
            ("onboarding", "Onboarding in progress", actions["open_onboarding"], "/onboarding"),
            ("statutory", "Statutory IDs not on file", missing_statutory, "/employees"),
            ("passports", "Passports expiring in 90 days", statutory["passports_expiring"],
             "/employees"),
        ]  # fmt: skip
        return [
            {"key": key, "label": label, "count": count, "link": link}
            for key, label, count, link in items
        ]

    result: dict = {
        "role": "HR",
        "scope": {
            "is_all": scope.is_all,
            "legal_entity_count": len(scope.legal_entity_ids) if not scope.is_all else None,
        },
    }
    if "headcount" in wanted:
        result.update(await once("headcount", _headcount))
    for section, compute in (
        ("today", _today),
        ("actions", _actions),
        ("pending_requests", _pending_requests),
        ("upcoming_birthdays", _birthdays),
        ("upcoming_anniversaries", _anniversaries),
        ("department_distribution", _departments),
        ("entity_distribution", _entities),
        ("recent_joiners", _recent_joiners),
        ("tenure", _tenure),
        ("kyc", _kyc_summary),
        ("org_summary", _org_summary),
        ("trends", _trends),
        ("exits", _exits),
        ("attendance_30d", _attendance_30d),
        ("vacancies", _vacancies),
        ("statutory", _statutory),
        ("worker_types", _worker_types),
        ("leave_by_department", _leave_by_department),
        ("lifecycle", _lifecycle),
        ("highlights_today", _highlights_today),
        ("scheduled_changes", _scheduled_changes),
        ("action_centre", _action_centre),
    ):
        if section in wanted:
            result[section] = await once({"kyc": "kyc_summary"}.get(section, section), compute)
    return result


# ─── Super admin dashboard ────────────────────────────────────────────────────


@router.get(
    "/super-admin",
    summary="Super admin / platform dashboard",
    dependencies=[require_permission("dashboard.hr")],
)
async def super_admin_dashboard(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    sections: str | None = Query(default=None, description="As for /v1/dashboard/hr"),
    legal_entity_id: str | None = Query(default=None, description="As for /v1/dashboard/hr"),
) -> dict:
    """Extends HR dashboard with system-health indicators."""
    scope = scope.for_permission("dashboard.hr")
    # Called as a plain function, so every parameter is passed: a default here would be
    # FastAPI's Query marker, not None.
    hr_data = await hr_dashboard(
        scope=scope,
        tenant_id=tenant_id,
        session=session,
        sections=sections,
        legal_entity_id=legal_entity_id,
    )

    system = {
        "api_status": "HEALTHY",
        "db_status": "HEALTHY",
        "last_checked": datetime.now(UTC).isoformat(),
    }

    return {**hr_data, "role": "SUPER_ADMIN", "system": system}


# ─── Customisable layout ──────────────────────────────────────────────────────
# Each HR/admin user arranges their own dashboard from the widget catalog
# (dashboard/widgets.py). The layout belongs to the signed-in account: there is no way to
# read or change anyone else's.

LAYOUT_DASHBOARDS = Literal["hr", "overview"]


async def _layout_response(session, tenant_id, principal, scope, dashboard: str):
    row = (
        (
            await session.execute(
                text("""
                    SELECT widgets FROM dashboard_layouts
                    WHERE tenant_id = CAST(:tid AS uuid) AND user_account_id = CAST(:uid AS uuid)
                      AND dashboard = :dashboard
                """),
                {
                    "tid": str(tenant_id),
                    "uid": str(principal.user_account_id),
                    "dashboard": dashboard,
                },
            )
        )
        .scalars()
        .first()
    )
    layout = (
        widgets.normalise(row, scope, dashboard)
        if row is not None
        else widgets.default_layout(scope, dashboard)
    )
    return LayoutResponse(
        dashboard=dashboard,
        widgets=[LayoutItem(**item) for item in layout],
        is_default=row is None,
        sections=",".join(
            s for s in widgets.SECTIONS if s in widgets.sections_for(layout, dashboard)
        ),
        catalog=[WidgetInfo(**w.public()) for w in widgets.available(scope, dashboard)],
    )


@router.get(
    "/layout",
    response_model=LayoutResponse,
    summary="Your dashboard layout, and the widgets you can add",
    dependencies=[require_permission("dashboard.hr")],
)
async def get_layout(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    dashboard: LAYOUT_DASHBOARDS = Query(default="hr"),
) -> LayoutResponse:
    scope = scope.for_permission("dashboard.hr")
    return await _layout_response(session, tenant_id, principal, scope, dashboard)


@router.put(
    "/layout",
    response_model=LayoutResponse,
    summary="Save your dashboard layout",
    dependencies=[require_permission("dashboard.hr")],
)
async def save_layout(
    body: LayoutUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    dashboard: LAYOUT_DASHBOARDS = Query(default="hr"),
) -> LayoutResponse:
    scope = scope.for_permission("dashboard.hr")
    clean = widgets.validate([item.model_dump() for item in body.widgets], scope, dashboard)
    await session.execute(
        text("""
            INSERT INTO dashboard_layouts (tenant_id, id, user_account_id, dashboard, widgets,
                                           updated_at)
            VALUES (CAST(:tid AS uuid), CAST(:id AS uuid), CAST(:uid AS uuid), :dashboard,
                    CAST(:widgets AS jsonb), now())
            ON CONFLICT (tenant_id, user_account_id, dashboard)
            DO UPDATE SET widgets = EXCLUDED.widgets, updated_at = now()
        """),
        {
            "tid": str(tenant_id),
            "id": str(uuid4()),
            "uid": str(principal.user_account_id),
            "dashboard": dashboard,
            "widgets": json.dumps(clean),
        },
    )
    return await _layout_response(session, tenant_id, principal, scope, dashboard)


@router.delete(
    "/layout",
    response_model=LayoutResponse,
    summary="Go back to the default dashboard layout",
    dependencies=[require_permission("dashboard.hr")],
)
async def reset_layout(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    dashboard: LAYOUT_DASHBOARDS = Query(default="hr"),
) -> LayoutResponse:
    scope = scope.for_permission("dashboard.hr")
    await session.execute(
        text("""
            DELETE FROM dashboard_layouts
            WHERE tenant_id = CAST(:tid AS uuid) AND user_account_id = CAST(:uid AS uuid)
              AND dashboard = :dashboard
        """),
        {"tid": str(tenant_id), "uid": str(principal.user_account_id), "dashboard": dashboard},
    )
    return await _layout_response(session, tenant_id, principal, scope, dashboard)

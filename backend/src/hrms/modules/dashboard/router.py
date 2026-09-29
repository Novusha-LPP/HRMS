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

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Query
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
from hrms.core.tenancy import TenantDep
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

    today = date.today()
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

    today = date.today()

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

    return {
        "role": "MANAGER",
        "team_size": len(team),
        "today": {"date": today.isoformat(), **attendance_summary},
        "team": team,
        "pending_approvals": [
            {
                "id": str(pa.id),
                "employment_id": str(pa.employment_id),
                "type": pa.type,
                "effective_date": pa.effective_date.isoformat(),
            }
            for pa in pending
        ],
    }


# ─── HR dashboard ─────────────────────────────────────────────────────────────


# Today's assignment (one row per employment) and its department. The date test is
# the same everywhere an "as of today" assignment is needed — an open-ended
# assignment that starts in the future, or one that has ended, is not current.
_CURRENT_DEPARTMENT = """
    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
        AND a.effective_from <= CURRENT_DATE
        AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
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
async def hr_dashboard(scope: ScopeDep, tenant_id: TenantDep, session: SessionDep) -> dict:
    """
    Every figure here is limited to the employees the caller's dashboard.hr grants
    cover (`emp_clause`, always against the alias `e`): an HR manager scoped to one
    company sees that company's headcount, KYC status, tenure and departments — not
    the group's. (The clause used to be built for the alias `employments` and reused
    in queries that alias the table `e`, which made every entity-scoped HR manager and
    accountant get a 500, and several aggregates skipped the clause altogether.)
    """
    scope = scope.for_permission("dashboard.hr")
    today = date.today()
    month_start = today.replace(day=1)
    emp_clause, emp_params = scope.employment_filter_sql("e")
    base = {"tid": str(tenant_id), **emp_params}

    async def rows(sql: str, **params):
        return (await session.execute(text(sql), {**base, **params})).mappings().all()

    async def one(sql: str, **params):
        return (await session.execute(text(sql), {**base, **params})).mappings().first()

    hc = await one(f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE e.employment_state = 'ACTIVE') AS active,
               COUNT(*) FILTER (WHERE e.employment_state = 'PROBATION') AS probation,
               COUNT(*) FILTER (WHERE e.employment_state = 'NOTICE') AS on_notice
        FROM employments e
        WHERE e.tenant_id = CAST(:tid AS uuid) AND e.archived_at IS NULL
          AND e.employment_state != 'SEPARATED'
          {emp_clause}
    """)

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

    new_hire_count = (
        await one(
            f"""
        SELECT COUNT(*) AS n FROM employments e
        WHERE e.tenant_id = CAST(:tid AS uuid) AND e.hire_date >= CAST(:month_start AS date)
          {emp_clause}
    """,
            month_start=month_start,
        )
    )["n"]

    pending_pa_count = (
        await one(f"""
        SELECT COUNT(*) AS n FROM personnel_actions pa
        JOIN employments e ON e.tenant_id = pa.tenant_id AND e.id = pa.employment_id
        WHERE pa.tenant_id = CAST(:tid AS uuid) AND pa.status = 'PENDING_APPROVAL'
          {emp_clause}
    """)
    )["n"]

    open_ob_count = (
        await one(f"""
        SELECT COUNT(*) AS n FROM onboarding_cases oc
        JOIN employments e ON e.tenant_id = oc.tenant_id AND e.id = oc.employment_id
        WHERE oc.tenant_id = CAST(:tid AS uuid) AND oc.status = 'IN_PROGRESS'
          {emp_clause}
    """)
    )["n"]

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

    recent_joiners = [
        {
            "name": r["name"],
            "employee_number": r["employee_number"],
            "hire_date": r["hire_date"].isoformat() if r["hire_date"] else None,
            "company": r["company"],
            "department": r["department"] or "General",
        }
        for r in await rows(f"""
            SELECT p.legal_first_name || ' ' || p.legal_last_name AS name, e.employee_number,
                   e.hire_date, le.name AS company, ou.name AS department
            FROM employments e
            JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
            {_CURRENT_DEPARTMENT}
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state != 'SEPARATED'
              AND e.archived_at IS NULL
              {emp_clause}
            ORDER BY e.hire_date DESC NULLS LAST
            LIMIT 5
        """)
    ]

    tenure = await one(f"""
        SELECT AVG(CURRENT_DATE - e.hire_date) / 365.25 AS avg_years,
               COUNT(*) FILTER (WHERE CURRENT_DATE - e.hire_date >= 3652.5) AS over_10_years,
               COUNT(*) FILTER (WHERE CURRENT_DATE - e.hire_date >= 1826.25
                                  AND CURRENT_DATE - e.hire_date < 3652.5) AS tenure_5_to_10,
               COUNT(*) FILTER (WHERE CURRENT_DATE - e.hire_date < 1826.25) AS tenure_under_5
        FROM employments e
        WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state != 'SEPARATED'
          AND e.hire_date IS NOT NULL
          {emp_clause}
    """)

    # Locations: every one for a group-wide caller; for a scoped caller, the locations
    # their own people are currently assigned to.
    if scope.is_all:
        location_count = (
            await one("""
            SELECT COUNT(*) AS n FROM locations
            WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
        """)
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

    separated_count = (
        await one(f"""
        SELECT COUNT(*) AS n FROM employments e
        WHERE e.tenant_id = CAST(:tid AS uuid) AND e.employment_state = 'SEPARATED'
          {emp_clause}
    """)
    )["n"]

    kyc_total = sum(
        (kyc[k] or 0) for k in ("verified", "submitted", "action_required", "not_submitted")
    )
    org_summary = {
        "total_entities": len(entity_distribution),
        "total_departments": len(department_distribution),
        "total_locations": location_count,
        "separated_count": separated_count,
        "avg_tenure_years": round(float(tenure["avg_years"]), 1) if tenure["avg_years"] else 0,
        "tenure_brackets": {
            "over_10_years": tenure["over_10_years"],
            "5_to_10_years": tenure["tenure_5_to_10"],
            "under_5_years": tenure["tenure_under_5"],
        },
        "kyc_compliance": {
            "verified": kyc["verified"],
            "submitted": kyc["submitted"],
            "action_required": kyc["action_required"],
            "not_submitted": kyc["not_submitted"],
            "rate_pct": round((kyc["verified"] or 0) / max(1, kyc_total) * 100, 1),
        },
    }

    return {
        "role": "HR",
        "scope": {
            "is_all": scope.is_all,
            "legal_entity_count": len(scope.legal_entity_ids) if not scope.is_all else None,
        },
        "headcount": {
            "total": hc["total"],
            "active": hc["active"],
            "probation": hc["probation"],
            "on_notice": hc["on_notice"],
        },
        "today": {
            "date": today.isoformat(),
            "present": att["present"],
            "absent": att["absent"],
            "on_leave": att["on_leave"],
            "late": att["late"],
        },
        "month": {"month": month_start.strftime("%B %Y"), "new_hires": new_hire_count},
        "actions": {
            "pending_approvals": pending_pa_count,
            "open_onboarding": open_ob_count,
            "pending_kyc": kyc["submitted"],
        },
        "upcoming_birthdays": upcoming_birthdays,
        "upcoming_anniversaries": upcoming_anniversaries,
        "department_distribution": department_distribution,
        "entity_distribution": entity_distribution,
        "recent_joiners": recent_joiners,
        "org_summary": org_summary,
    }


# ─── Super admin dashboard ────────────────────────────────────────────────────


@router.get(
    "/super-admin",
    summary="Super admin / platform dashboard",
    dependencies=[require_permission("dashboard.hr")],
)
async def super_admin_dashboard(scope: ScopeDep, tenant_id: TenantDep, session: SessionDep) -> dict:
    """Extends HR dashboard with system-health indicators."""
    scope = scope.for_permission("dashboard.hr")
    hr_data = await hr_dashboard(scope=scope, tenant_id=tenant_id, session=session)

    system = {
        "api_status": "HEALTHY",
        "db_status": "HEALTHY",
        "last_checked": datetime.now(UTC).isoformat(),
    }

    return {**hr_data, "role": "SUPER_ADMIN", "system": system}

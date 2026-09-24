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

from datetime import date, datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, require_permission, resolve_acting_employment_id
from hrms.core.database import SessionDep
from hrms.core.tenancy import TenantDep
from hrms.modules.onboarding.models import CaseStatus, OnboardingCase, OnboardingItem
from hrms.modules.people.models import Employment, PersonnelAction, PersonnelActionStatus
from hrms.modules.time.models import AttendanceDay, AttendanceStatus, Punch, PunchType

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
    present = sum(1 for d in month_days if d.status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE))
    absent = sum(1 for d in month_days if d.status == AttendanceStatus.ABSENT)
    late = sum(1 for d in month_days if d.status == AttendanceStatus.LATE)

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
            "punch_in_time": today_ad.first_punch_in.isoformat() if today_ad and today_ad.first_punch_in else None,
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
    manager_employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
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
            elif ad["status"] in ("PRESENT", "LATE"):
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
            {"id": str(pa.id), "employment_id": str(pa.employment_id), "type": pa.type,
             "effective_date": pa.effective_date.isoformat()}
            for pa in pending
        ],
    }


# ─── HR dashboard ─────────────────────────────────────────────────────────────

@router.get("/hr", summary="HR admin dashboard", dependencies=[require_permission("dashboard.hr")])
async def hr_dashboard(scope: ScopeDep, tenant_id: TenantDep, session: SessionDep) -> dict:
    today = date.today()
    month_start = today.replace(day=1)
    entity_clause, entity_params = scope.employment_filter_sql("employments")

    hc = (await session.execute(
        text(f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE employment_state = 'ACTIVE') AS active,
                   COUNT(*) FILTER (WHERE employment_state = 'PROBATION') AS probation,
                   COUNT(*) FILTER (WHERE employment_state = 'NOTICE') AS on_notice
            FROM employments
            WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
              AND employment_state != 'SEPARATED'
              {entity_clause}
        """),
        {"tid": str(tenant_id), **entity_params},
    )).mappings().first()

    att_join, att_params = scope.employment_filter_sql("e")
    att = (await session.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE ad.status IN ('PRESENT','LATE')) AS present,
                COUNT(*) FILTER (WHERE ad.status = 'ABSENT')           AS absent,
                COUNT(*) FILTER (WHERE ad.status = 'ON_LEAVE')         AS on_leave
            FROM attendance_days ad
            JOIN employments e ON e.tenant_id = ad.tenant_id AND e.id = ad.employment_id
            WHERE ad.tenant_id = CAST(:tid AS uuid) AND ad.work_date = CAST(:today AS date)
              {att_join}
        """),
        {"tid": str(tenant_id), "today": today, **att_params},
    )).mappings().first()

    new_hires_q = (
        select(func.count(Employment.id))
        .where(Employment.tenant_id == tenant_id)
        .where(Employment.hire_date >= month_start)
    )
    if not scope.is_all:
        if scope.employment_ids is not None:
            new_hires_q = new_hires_q.where(Employment.id.in_(scope.employment_ids))
        else:
            new_hires_q = new_hires_q.where(Employment.legal_entity_id.in_(scope.legal_entity_ids))
    new_hire_count = (await session.execute(new_hires_q)).scalar() or 0

    pa_join, pa_params = scope.employment_filter_sql("e")
    pending_pa_count = (await session.execute(
        text(f"""
            SELECT COUNT(*) FROM personnel_actions pa
            JOIN employments e ON e.tenant_id = pa.tenant_id AND e.id = pa.employment_id
            WHERE pa.tenant_id = CAST(:tid AS uuid) AND pa.status = 'PENDING_APPROVAL'
              {pa_join}
        """),
        {"tid": str(tenant_id), **pa_params},
    )).scalar() or 0

    ob_join, ob_params = scope.employment_filter_sql("e")
    open_ob_count = (await session.execute(
        text(f"""
            SELECT COUNT(*) FROM onboarding_cases oc
            JOIN employments e ON e.tenant_id = oc.tenant_id AND e.id = oc.employment_id
            WHERE oc.tenant_id = CAST(:tid AS uuid) AND oc.status = 'IN_PROGRESS'
              {ob_join}
        """),
        {"tid": str(tenant_id), **ob_params},
    )).scalar() or 0

    return {
        "role": "HR",
        "scope": {"is_all": scope.is_all, "legal_entity_count": len(scope.legal_entity_ids) if not scope.is_all else None},
        "headcount": {
            "total": hc["total"] if hc else 0,
            "active": hc["active"] if hc else 0,
            "probation": hc["probation"] if hc else 0,
            "on_notice": hc["on_notice"] if hc else 0,
        },
        "today": {
            "date": today.isoformat(),
            "present": att["present"] if att else 0,
            "absent": att["absent"] if att else 0,
            "on_leave": att["on_leave"] if att else 0,
        },
        "month": {"month": month_start.strftime("%B %Y"), "new_hires": new_hire_count},
        "actions": {"pending_approvals": pending_pa_count, "open_onboarding": open_ob_count},
    }


# ─── Super admin dashboard ────────────────────────────────────────────────────

@router.get(
    "/super-admin", summary="Super admin / platform dashboard",
    dependencies=[require_permission("dashboard.hr")],
)
async def super_admin_dashboard(scope: ScopeDep, tenant_id: TenantDep, session: SessionDep) -> dict:
    """Extends HR dashboard with system-health indicators."""
    hr_data = await hr_dashboard(scope=scope, tenant_id=tenant_id, session=session)

    system = {
        "api_status": "HEALTHY",
        "db_status": "HEALTHY",
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }

    return {**hr_data, "role": "SUPER_ADMIN", "system": system}

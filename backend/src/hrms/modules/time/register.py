"""
Attendance register — one employee's attendance day by day, and HR's direct edit of a day.

GET /v1/time/register/employees              — find an employee (people.read scope)
GET /v1/time/register/{employment_id}         — every day in a range, with its punches
PUT /v1/time/register/{employment_id}/{date}  — replace a day's punches (corrections.write)

A direct edit is the HR equivalent of an approved correction: the old punches are voided (never
deleted), the new ones are recorded as MANUAL with the reason, the day is recalculated through the
same engine as the time clock, and an APPROVED correction record names who did it and why — so the
employee sees it in their corrections history. Nobody can edit their own attendance this way.
"""

from collections import Counter
from datetime import date, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, read_scope, require_permission
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, is_working_day, now_utc, to_tz
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.corrections.models import (
    AttendanceCorrectionRequest,
    CorrectionApprovalAction,
    CorrectionStatus,
)
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.groups import group_on, group_spans
from hrms.modules.time.holidays import holiday_scope_sql
from hrms.modules.time.models import AttendanceDay, Punch
from hrms.modules.time.schemas import (
    DayPunchesUpdate,
    RegisterCompany,
    RegisterDay,
    RegisterDepartment,
    RegisterEmployee,
    RegisterFilters,
    RegisterPunch,
    RegisterResponse,
)
from hrms.modules.time.service import (
    MAX_OPEN_SESSION,
    events_for_day,
    lock_day,
    recompute_day,
    work_date_for,
)

router = APIRouter(prefix="/v1/time/register", tags=["Time & Attendance"])

MAX_RANGE_DAYS = 62
DIRECT_EDIT = "DIRECT_EDIT"
NEXT = {
    None: {"IN"},
    "OUT": {"IN"},
    "IN": {"OUT", "BREAK_START"},
    "BREAK_START": {"BREAK_END", "OUT"},
    "BREAK_END": {"OUT", "BREAK_START"},
}
LABEL = {
    "IN": "check-in",
    "OUT": "check-out",
    "BREAK_START": "break start",
    "BREAK_END": "break end",
}

# Both the picker and its filters use the complete people.read scope. Team members
# belong to their parent department, as they do in the employee directory.
_REGISTER_PEOPLE_SQL = """
    SELECT e.id, e.employee_number, e.legal_entity_id, le.name AS company,
           p.legal_first_name || ' ' || p.legal_last_name AS name,
           CASE WHEN ou.type = 'TEAM' THEN parent_ou.id ELSE ou.id END AS department_id,
           CASE WHEN ou.type = 'TEAM' THEN parent_ou.name ELSE ou.name END AS department
    FROM employments e
    JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
         AND a.effective_from <= CURRENT_DATE
         AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
    LEFT JOIN org_units parent_ou ON parent_ou.tenant_id = ou.tenant_id
         AND parent_ou.id = ou.parent_id
    WHERE e.tenant_id = :tid AND e.archived_at IS NULL
"""


@router.get(
    "/filters",
    response_model=RegisterFilters,
    summary="Companies and departments in the attendance register's people scope",
    dependencies=[require_permission("people.read")],
)
async def register_filters(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> RegisterFilters:
    clause, params = scope.for_permission("people.read").employment_filter_sql("e")
    rows = await session.execute(
        text(f"""
            SELECT DISTINCT legal_entity_id, company, department_id, department
            FROM ({_REGISTER_PEOPLE_SQL} {clause}) people
            ORDER BY company, department, legal_entity_id, department_id
        """),
        {"tid": tenant_id, **params},
    )
    companies = {}
    departments = []
    for row in rows.mappings():
        entity_id = to_typed_id("legal_entity", row["legal_entity_id"])
        companies[entity_id] = RegisterCompany(id=entity_id, name=row["company"])
        if row["department_id"]:
            departments.append(
                RegisterDepartment(
                    id=to_typed_id("org_unit", row["department_id"]),
                    name=row["department"],
                    legal_entity_id=entity_id,
                )
            )
    return RegisterFilters(companies=list(companies.values()), departments=departments)


@router.get(
    "/employees",
    response_model=list[RegisterEmployee],
    summary="Find an employee for the attendance register",
    dependencies=[require_permission("people.read")],
)
async def find_employees(
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    legal_entity_id: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
) -> list[RegisterEmployee]:
    clause, params = scope.for_permission("people.read").employment_filter_sql("e")
    filters = ""
    if legal_entity_id:
        filters += " AND legal_entity_id = :entity_id"
        params["entity_id"] = to_uuid(legal_entity_id)
    if department_id:
        filters += " AND department_id = :department_id"
        params["department_id"] = to_uuid(department_id)
    rows = await session.execute(
        text(f"""
            SELECT * FROM ({_REGISTER_PEOPLE_SQL} {clause}) people
            WHERE (:search = '' OR strpos(lower(name), :search) > 0
                   OR strpos(lower(employee_number), :search) > 0)
              {filters}
            ORDER BY name, id
            LIMIT :limit OFFSET :offset
        """),
        {
            "tid": tenant_id,
            "search": search.strip().lower(),
            "limit": limit,
            "offset": offset,
            **params,
        },
    )
    return [
        RegisterEmployee(
            employment_id=to_typed_id("employment", r["id"]),
            employee_number=r["employee_number"],
            name=r["name"],
            legal_entity_id=to_typed_id("legal_entity", r["legal_entity_id"]),
            company=r["company"],
            department_id=to_typed_id("org_unit", r["department_id"])
            if r["department_id"]
            else None,
            department=r["department"],
        )
        for r in rows.mappings()
    ]


@router.get(
    "/{employment_id}",
    response_model=RegisterResponse,
    summary="An employee's attendance, day by day, with every punch",
)
async def employee_register(
    employment_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    from_date: date = Query(...),
    to_date: date = Query(...),
) -> RegisterResponse:
    if to_date < from_date or (to_date - from_date).days >= MAX_RANGE_DAYS:
        raise HTTPException(422, f"Choose a range of 1 to {MAX_RANGE_DAYS} days")
    emp = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, read_scope(scope, "people.read"), emp)
    employee = await _employee(session, tenant_id, emp)
    first = max(from_date, employee["hire_date"])
    last = min(to_date, employee["separation_date"] or to_date)
    days = []
    if first <= last:
        context = await _range_context(session, tenant_id, emp, employee, first, last)
        day = first
        while day <= last:
            days.append(await _register_day(session, tenant_id, emp, day, context))
            day += timedelta(days=1)
    return RegisterResponse(
        employment_id=to_typed_id("employment", emp),
        employee_number=employee["employee_number"],
        name=employee["name"],
        department=employee["department"],
        designation=employee["designation"],
        from_date=from_date,
        to_date=to_date,
        days=days,
    )


@router.put(
    "/{employment_id}/{work_date}",
    response_model=RegisterDay,
    summary="Replace a day's punches directly (HR correction, no approval)",
    dependencies=[require_permission("corrections.write")],
)
async def edit_day(
    employment_id: str,
    work_date: date,
    body: DayPunchesUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> RegisterDay:
    emp = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope.for_permission("corrections.write"), emp)
    if emp == principal.employment_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can't edit your own attendance — ask another administrator, or request a "
            "correction",
        )
    employee = await _employee(session, tenant_id, emp)
    if work_date < employee["hire_date"] or (
        employee["separation_date"] and work_date >= employee["separation_date"]
    ):
        raise HTTPException(422, "The employee wasn't employed on that day")
    if work_date > business_today():
        raise HTTPException(422, "A future day can't be edited")
    policy = await resolve_policy(emp, work_date, session, tenant_id)
    ad = await lock_day(session, tenant_id, emp, work_date)
    wanted = sorted(body.punches, key=lambda p: p.punched_at)
    _validate(wanted, work_date, policy)

    existing = await events_for_day(session, tenant_id, emp, work_date, policy)
    keep = Counter((p.punch_type, p.punched_at) for p in wanted)
    void = []
    for event in existing:
        key = (event.punch_type, event.punched_at)
        if keep[key]:
            keep[key] -= 1
        else:
            void.append(event)
    unchanged = Counter((e.punch_type, e.punched_at) for e in existing if e not in void)
    added = [p for p in wanted if not _take(unchanged, (p.punch_type, p.punched_at))]
    if not void and not added:
        raise HTTPException(400, "Nothing changed")

    actor = principal.user_account_id
    stamp = now_utc()
    for event in void:
        session.add(
            Punch(
                tenant_id=tenant_id,
                id=uuid4(),
                employment_id=emp,
                work_date=work_date,
                punch_type="VOID",
                punched_at=event.punched_at,
                source="MANUAL",
                is_corrected=True,
                original_punch_id=event.id,
                correction_reason=body.reason,
                recorded_at=stamp,
                recorded_by=actor,
            )
        )
    for p in added:
        session.add(
            Punch(
                tenant_id=tenant_id,
                id=uuid4(),
                employment_id=emp,
                work_date=work_date,
                punch_type=p.punch_type,
                punched_at=p.punched_at,
                source="MANUAL",
                is_corrected=True,
                correction_reason=body.reason,
                recorded_at=stamp,
                recorded_by=actor,
            )
        )
    ins = [p.punched_at for p in wanted if p.punch_type == "IN"]
    outs = [p.punched_at for p in wanted if p.punch_type == "OUT"]
    correction = AttendanceCorrectionRequest(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=emp,
        work_date=work_date,
        correction_type=DIRECT_EDIT,
        requested_punch_in=min(ins) if ins else None,
        requested_punch_out=max(outs) if outs else None,
        reason=body.reason,
        status=CorrectionStatus.APPROVED,
        current_level=1,
        total_levels=1,
        submitted_at=stamp,
        recorded_at=stamp,
        recorded_by=actor,
    )
    session.add(correction)
    session.add(
        CorrectionApprovalAction(
            tenant_id=tenant_id,
            id=uuid4(),
            correction_id=correction.id,
            action="APPROVE",
            level=1,
            approver_employment_id=principal.employment_id,
            approver_user_account_id=actor,
            comments="Edited directly in the attendance register",
            actioned_at=stamp,
            recorded_at=stamp,
        )
    )
    await session.flush()

    ad = await recompute_day(session, tenant_id, emp, work_date, policy, ad, clear_override=True)
    if ad.review_flags and ad.reviewed_at is None:
        # HR set these punches themselves: that is the review. Held overtime / comp-off follow.
        ad.reviewed_by = actor
        ad.reviewed_at = stamp
        ad = await recompute_day(session, tenant_id, emp, work_date, policy, ad)

    context = await _range_context(session, tenant_id, emp, employee, work_date, work_date)
    return await _register_day(session, tenant_id, emp, work_date, context)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _take(counter: Counter, key) -> bool:
    if counter[key]:
        counter[key] -= 1
        return True
    return False


def _validate(punches, work_date, policy) -> None:
    """The same sequence the time clock enforces, inside the day's 24-hour window."""
    now = now_utc()
    previous = None
    first_in = None
    for i, p in enumerate(punches):
        local = to_tz(p.punched_at, policy.timezone)
        at = f"{LABEL[p.punch_type]} at {local:%d %b %H:%M}"
        if p.punched_at > now:
            raise HTTPException(422, f"The {at} is in the future")
        if i and p.punched_at == punches[i - 1].punched_at:
            raise HTTPException(422, f"Two punches share the same time ({local:%d %b %H:%M})")
        if p.punch_type not in NEXT[previous]:
            expected = " or ".join(LABEL[k] for k in sorted(NEXT[previous]))
            raise HTTPException(422, f"The {at} is out of order — expected a {expected}")
        if p.punch_type == "IN":
            if work_date_for(p.punched_at, policy) != work_date:
                raise HTTPException(422, f"The {at} doesn't fall on {work_date:%d %b %Y}")
            first_in = first_in or p.punched_at
        elif first_in and p.punched_at - first_in > MAX_OPEN_SESSION:
            raise HTTPException(422, f"The {at} is more than 24 hours after the first check-in")
        previous = p.punch_type


async def _employee(session, tenant_id, emp):
    row = (
        (
            await session.execute(
                text("""
                    SELECT e.employee_number, e.hire_date, e.separation_date, e.legal_entity_id,
                           p.legal_first_name || ' ' || p.legal_last_name AS name,
                           CASE WHEN ou.type = 'TEAM' THEN parent_ou.name ELSE ou.name END
                               AS department,
                           j.title AS designation
                    FROM employments e
                    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                    LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
                         AND a.effective_from <= CURRENT_DATE
                         AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
                    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
                    LEFT JOIN org_units parent_ou ON parent_ou.tenant_id = ou.tenant_id
                         AND parent_ou.id = ou.parent_id
                    LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
                    WHERE e.tenant_id = :tid AND e.id = :eid
                """),
                {"tid": tenant_id, "eid": emp},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return row


async def _range_context(session, tenant_id, emp, employee, first, last):
    stored = {
        ad.work_date: ad
        for ad in (
            await session.execute(
                select(AttendanceDay)
                .where(AttendanceDay.tenant_id == tenant_id)
                .where(AttendanceDay.employment_id == emp)
                .where(AttendanceDay.work_date >= first)
                .where(AttendanceDay.work_date <= last)
            )
        ).scalars()
    }
    holidays = {
        r["holiday_date"]: r["name"]
        for r in (
            await session.execute(
                text(f"""
                    SELECT holiday_date, name FROM holidays h
                    WHERE tenant_id = :tid AND archived_at IS NULL AND is_optional = false
                      AND {holiday_scope_sql()}
                      AND holiday_date BETWEEN :first AND :last
                """),
                {"tid": tenant_id, "eid": emp, "first": first, "last": last},
            )
        ).mappings()
    }
    leaves = {}
    for r in (
        await session.execute(
            text("""
                SELECT la.from_date, la.to_date, lt.name
                FROM leave_applications la
                JOIN leave_types lt ON lt.tenant_id = la.tenant_id AND lt.id = la.leave_type_id
                WHERE la.tenant_id = :tid AND la.employment_id = :eid AND la.status = 'APPROVED'
                  AND la.from_date <= :last AND la.to_date >= :first
            """),
            {"tid": tenant_id, "eid": emp, "first": first, "last": last},
        )
    ).mappings():
        day = max(r["from_date"], first)
        while day <= min(r["to_date"], last):
            leaves[day] = r["name"]
            day += timedelta(days=1)
    groups = await group_spans(session, tenant_id, [emp], first, last)
    return {
        "stored": stored,
        "holidays": holidays,
        "leaves": leaves,
        "groups": groups.get(emp),
        "today": business_today(),
    }


async def _register_day(session, tenant_id, emp, day, context) -> RegisterDay:
    policy = await resolve_policy(emp, day, session, tenant_id)
    events = await events_for_day(session, tenant_id, emp, day, policy)
    ad = context["stored"].get(day)
    holiday = context["holidays"].get(day)
    leave = context["leaves"].get(day)
    working = is_working_day(day, policy.work_days, policy.saturday_pattern)
    marked = group_on(context.get("groups"), day) is not None  # time/groups.py
    if ad and ad.first_punch_in:
        state = ad.status
    elif leave:
        state = "ON_LEAVE"
    elif marked and ad and ad.status_override:
        state = ad.status  # marked present / absent (present on a day off: off-day work)
    elif holiday:
        state = "HOLIDAY"
    elif not working:
        state = "WEEKEND"
    elif day > context["today"]:
        state = "UPCOMING"
    elif marked:
        state = "NOT_MARKED"  # a marked day nobody has marked yet is not an absence
    else:
        state = ad.status if ad and ad.status != "PENDING" else "ABSENT"
    flags = ad.review_flags.split(",") if ad and ad.review_flags else []
    return RegisterDay(
        work_date=day,
        status=state,
        is_off_day=bool(holiday) or not working,
        holiday_name=holiday,
        leave_type=leave,
        attendance_day_id=to_typed_id("attendance_day", ad.id) if ad else None,
        first_punch_in=ad.first_punch_in if ad else None,
        last_punch_out=ad.last_punch_out if ad else None,
        effective_minutes=ad.effective_minutes if ad else 0,
        gross_minutes=ad.gross_minutes if ad else 0,
        break_minutes=ad.break_minutes if ad else 0,
        late_by_minutes=ad.late_by_minutes if ad else 0,
        early_departure_minutes=ad.early_departure_minutes if ad else 0,
        ot_minutes=ad.ot_minutes if ad else 0,
        ot_status=ad.ot_status if ad else "NONE",
        comp_off_days=ad.comp_off_days if ad else 0,
        review_flags=flags,
        needs_review=bool(flags) and ad.reviewed_at is None,
        is_locked=bool(ad and ad.is_locked),
        shift_start=policy.expected_start_time.strftime("%H:%M"),
        shift_end=policy.expected_end_time.strftime("%H:%M"),
        timezone=policy.timezone,
        policy_break_minutes=policy.break_minutes,
        grace_late_minutes=policy.grace_late_minutes,
        grace_early_minutes=policy.grace_early_departure_minutes,
        standard_minutes=policy.standard_minutes,
        half_day_minutes=policy.standard_minutes * policy.half_day_threshold_pct // 100,
        punches=[
            RegisterPunch(
                id=to_typed_id("punch", e.id),
                punch_type=e.punch_type,
                punched_at=e.punched_at,
                source=e.source,
                is_corrected=e.is_corrected,
                correction_reason=e.correction_reason,
            )
            for e in events
        ],
    )

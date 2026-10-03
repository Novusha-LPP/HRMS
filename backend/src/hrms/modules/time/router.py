"""
Time module — punch in/out, today status, attendance history.

POST /v1/time/punches           — record a punch (in or out)
GET  /v1/time/today             — today's status for the requesting employee
GET  /v1/time/attendance-days   — computed attendance days

All attendance calculations are policy-driven via the policy engine.
No hard-coded thresholds or rules.

employment_id here used to be whatever the client sent — meaning any
authenticated caller could punch in as someone else, or read anyone's
attendance history, just by changing a query parameter. It now defaults to
the caller's own employment and is checked against their scope if they ask
for someone else's (a manager checking a direct report's history, say).
"""

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    ScopeDep,
    authorize_employment,
    authorize_write,
    read_scope,
    require_permission,
    resolve_acting_employment_id,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, calc_lateness, is_working_day, now_utc, to_tz
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.approvals import service as approval_flow
from hrms.modules.policy.engine import PolicyResolver, resolve_policy
from hrms.modules.time.models import (
    AttendanceDay,
    AttendanceStatus,
    Holiday,
    OvertimeStatus,
    Punch,
    PunchSource,
    PunchType,
)
from hrms.modules.time.presence import classify, is_late
from hrms.modules.time.schemas import (
    AttendanceDayResponse,
    DailyAnalysisResponse,
    DailyEmployeeRecord,
    DailyMetrics,
    DepartmentAttendanceStat,
    HolidayCreate,
    HolidayResponse,
    HourlyArrivalStat,
    OvertimeReviewRequest,
    PendingOvertimeItem,
    PunchCreate,
    PunchResponse,
    TodayStatusResponse,
)
from hrms.modules.time.service import events_for_day, lock_day, recompute_day, work_date_for

router = APIRouter(prefix="/v1/time", tags=["Time & Attendance"])


@router.post(
    "/punches", response_model=PunchResponse, status_code=201, summary="Record a punch (in or out)"
)
async def create_punch(
    body: PunchCreate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id_header: str | None = Query(
        default=None,
        alias="employment-id",
        description="Typed employment ID (emp_...). Defaults to your own.",
    ),
) -> PunchResponse:
    emp_uuid = resolve_acting_employment_id(principal, employment_id_header)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    await authorize_write(session, tenant_id, scope, principal, emp_uuid, "time.write")
    if body.punched_at is not None or body.source not in (PunchSource.WEB, PunchSource.MOBILE):
        raise HTTPException(
            422, "Historical and device punches must use an authorized correction workflow"
        )
    uid = uuid4()
    punched_at = now_utc()
    policy = await resolve_policy(emp_uuid, punched_at.date(), session, tenant_id)
    day = work_date_for(punched_at, policy)
    policy = await resolve_policy(emp_uuid, day, session, tenant_id)
    ad = await lock_day(session, tenant_id, emp_uuid, day)
    events = await events_for_day(session, tenant_id, emp_uuid, day, policy)
    previous = events[-1].punch_type if events else None
    allowed = {
        None: {"IN"},
        "OUT": {"IN"},
        "IN": {"OUT", "BREAK_START"},
        "BREAK_START": {"BREAK_END", "OUT"},
        "BREAK_END": {"OUT", "BREAK_START"},
    }
    if body.punch_type not in allowed.get(previous, set()):
        raise HTTPException(409, "Invalid punch sequence; use a correction for missing events")
    punch = Punch(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        punch_type=body.punch_type,
        punched_at=punched_at,
        work_date=day,
        source=body.source,
        latitude=body.latitude,
        longitude=body.longitude,
        device_id=body.device_id,
        recorded_by=principal.user_account_id,
        recorded_at=now_utc(),
    )
    session.add(punch)
    await session.flush()
    await recompute_day(session, tenant_id, emp_uuid, day, policy, ad)

    return PunchResponse(
        id=to_typed_id("punch", uid),
        employment_id=to_typed_id("employment", emp_uuid),
        punch_type=punch.punch_type,
        punched_at=punch.punched_at,
        source=punch.source,
        latitude=punch.latitude,
        longitude=punch.longitude,
        is_corrected=punch.is_corrected,
    )


@router.get(
    "/today", response_model=TodayStatusResponse, summary="Today's punch status for an employee"
)
async def today_status(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
    work_date: date | None = Query(
        default=None, description="Target calendar date (defaults to today)"
    ),
) -> TodayStatusResponse:
    scope = read_scope(scope, "people.read")
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    policy = await resolve_policy(emp_uuid, now_utc().date(), session, tenant_id)
    target_date = work_date if isinstance(work_date, date) else work_date_for(now_utc(), policy)
    policy = await resolve_policy(emp_uuid, target_date, session, tenant_id)
    ad_row = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.employment_id == emp_uuid)
        .where(AttendanceDay.work_date == target_date)
    )
    ad = ad_row.scalars().first()

    punches = await events_for_day(session, tenant_id, emp_uuid, target_date, policy)

    is_punched_in = False
    if punches:
        last = punches[-1]
        is_punched_in = last.punch_type in (PunchType.IN, PunchType.BREAK_END)

    return TodayStatusResponse(
        employment_id=to_typed_id("employment", emp_uuid),
        work_date=target_date,
        is_punched_in=is_punched_in,
        first_punch_in=ad.first_punch_in if ad else None,
        last_punch_out=ad.last_punch_out if ad else None,
        effective_minutes=ad.effective_minutes if ad else 0,
        status=ad.status if ad else AttendanceStatus.ABSENT,
        punches=[
            PunchResponse(
                id=to_typed_id("punch", p.id),
                employment_id=to_typed_id("employment", p.employment_id),
                punch_type=p.punch_type,
                punched_at=p.punched_at,
                source=p.source,
                latitude=p.latitude,
                longitude=p.longitude,
                is_corrected=p.is_corrected,
            )
            for p in punches
        ],
    )


@router.get(
    "/attendance-days",
    response_model=list[AttendanceDayResponse],
    summary="Attendance days for an employee in a date range",
)
async def list_attendance_days(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    from_date: date = Query(...),
    to_date: date = Query(...),
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
) -> list[AttendanceDayResponse]:
    scope = read_scope(scope, "people.read")
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    rows = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.employment_id == emp_uuid)
        .where(AttendanceDay.work_date >= from_date)
        .where(AttendanceDay.work_date <= to_date)
        .order_by(AttendanceDay.work_date.desc())  # type: ignore[attr-defined]
    )
    return [_attendance_day_response(r) for r in rows.scalars()]


# ─── Holiday calendar ─────────────────────────────────────────────────────────
#
# Gated with leave.write, not a new permission — HR maintains this the same
# way it maintains the leave-type catalog (a tenant-wide reference list), and
# it feeds both attendance status here and working-day counting in leave
# applications (see working_days_between in leave/router.py).


@router.get("/holidays", response_model=list[HolidayResponse], summary="Tenant holiday calendar")
async def list_holidays(
    tenant_id: TenantDep,
    session: SessionDep,
    year: int | None = Query(default=None),
) -> list[HolidayResponse]:
    q = (
        select(Holiday).where(Holiday.tenant_id == tenant_id).where(Holiday.archived_at == None)  # noqa: E711
    )
    if year:
        q = q.where(Holiday.holiday_date >= date(year, 1, 1)).where(
            Holiday.holiday_date <= date(year, 12, 31)
        )
    rows = await session.execute(q.order_by(Holiday.holiday_date))  # type: ignore[attr-defined]
    return [_holiday_response(h) for h in rows.scalars()]


@router.post(
    "/holidays",
    response_model=HolidayResponse,
    status_code=201,
    dependencies=[require_permission("leave.write")],
)
async def create_holiday(
    body: HolidayCreate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> HolidayResponse:
    h = Holiday(
        tenant_id=tenant_id,
        id=uuid4(),
        holiday_date=body.holiday_date,
        name=body.name,
        legal_entity_id=to_uuid(body.legal_entity_id) if body.legal_entity_id else None,
        is_optional=body.is_optional,
        recorded_at=now_utc(),
    )
    session.add(h)
    await session.flush()
    return _holiday_response(h)


@router.delete(
    "/holidays/{holiday_id}", status_code=204, dependencies=[require_permission("leave.write")]
)
async def delete_holiday(
    holiday_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    h_uuid = to_uuid(holiday_id)
    row = await session.execute(
        select(Holiday).where(Holiday.tenant_id == tenant_id).where(Holiday.id == h_uuid)
    )
    h = row.scalars().first()
    if not h:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found")
    h.archived_at = now_utc()
    session.add(h)
    await session.flush()


# ─── Overtime review ──────────────────────────────────────────────────────────
#
# compute_day() has always correctly computed OT from the policy engine; it
# just used to be discarded on write. Reusing corrections.approve as the gate
# here rather than inventing a new permission string — both are "review an
# attendance-adjacent request from someone in my scope" actions, and every
# role that already approves corrections (MANAGER, HR_MANAGER) is exactly
# who should be reviewing OT too.


@router.get(
    "/overtime/pending",
    response_model=list[PendingOvertimeItem],
    summary="Attendance days with unreviewed overtime, within the caller's scope",
    dependencies=[require_permission("corrections.approve")],
)
async def list_pending_overtime(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
) -> list[PendingOvertimeItem]:
    scope = scope.for_permission("corrections.approve")
    clause, params = scope.employment_filter_sql("e")
    date_clause = ""
    if from_date:
        date_clause += " AND ad.work_date >= :from_date"
        params["from_date"] = from_date
    if to_date:
        date_clause += " AND ad.work_date <= :to_date"
        params["to_date"] = to_date

    rows = (
        (
            await session.execute(
                text(f"""
                SELECT ad.id, ad.employment_id, ad.work_date, ad.effective_minutes,
                ad.ot_minutes, ad.ot_status,
                       e.employee_number, p.legal_first_name || ' ' || p.legal_last_name AS
                       name, ou.name AS department
                FROM attendance_days ad
                JOIN employments e ON e.tenant_id = ad.tenant_id AND e.id = ad.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
                AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE) AND
                a.effective_from <= CURRENT_DATE
                LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
                WHERE ad.tenant_id = CAST(:tid AS uuid) AND ad.ot_status = 'PENDING'
                {clause} {date_clause}
                ORDER BY ad.work_date DESC
            """),
                {"tid": str(tenant_id), **params},
            )
        )
        .mappings()
        .all()
    )

    return [
        PendingOvertimeItem(
            attendance_day_id=to_typed_id("attendance_day", r["id"]),
            employment_id=to_typed_id("employment", r["employment_id"]),
            employee_number=r["employee_number"],
            name=r["name"],
            department=r["department"],
            work_date=r["work_date"],
            effective_minutes=r["effective_minutes"],
            ot_minutes=r["ot_minutes"],
            ot_status=r["ot_status"],
        )
        for r in rows
    ]


@router.patch(
    "/overtime/{attendance_day_id}",
    response_model=AttendanceDayResponse,
    summary="Approve or reject a day's overtime",
)
async def review_overtime(
    attendance_day_id: str,
    body: OvertimeReviewRequest,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> AttendanceDayResponse:
    ad_uuid = to_uuid(attendance_day_id)
    row = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.id == ad_uuid)
        .with_for_update()
    )
    ad = row.scalars().first()
    if not ad:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance day not found")
    dynamic = await approval_flow.current_instance(session, tenant_id, "OVERTIME", ad.id)
    if dynamic and dynamic.status == "PENDING":
        await approval_flow.require_actor(session, tenant_id, "OVERTIME", ad.id, principal)
    else:
        scope = scope.for_permission("corrections.approve")
        await authorize_employment(session, tenant_id, scope, ad.employment_id)
    if ad.ot_status != OvertimeStatus.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This day's overtime is already {ad.ot_status}, not pending",
        )
    if dynamic and dynamic.status == "PENDING":
        final = await approval_flow.record_decision(
            session,
            tenant_id,
            "OVERTIME",
            ad.id,
            principal,
            "APPROVE" if body.status == "APPROVED" else "REJECT",
            body.notes,
        )
        if not final:
            await session.flush()
            return _attendance_day_response(ad)
    if ad.employment_id == principal.employment_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't approve your own overtime")

    ad.ot_status = OvertimeStatus.APPROVED if body.status == "APPROVED" else OvertimeStatus.REJECTED
    ad.ot_reviewed_by = principal.employment_id
    ad.ot_reviewed_at = now_utc()
    ad.ot_review_notes = body.notes
    session.add(ad)
    await session.flush()
    return _attendance_day_response(ad)


@dataclass(slots=True, kw_only=True)
class _DailyRecord:
    employment_id: UUID
    employee_number: str
    name: str
    email: str | None = None
    department: str | None = None
    designation: str | None = None
    location: str | None = None
    status: str
    first_punch_in: datetime | None = None
    last_punch_out: datetime | None = None
    effective_minutes: int = 0
    gross_minutes: int = 0
    break_minutes: int = 0
    late_by_minutes: int = 0
    early_departure_minutes: int = 0
    overtime_minutes: int = 0
    overtime_status: OvertimeStatus = OvertimeStatus.NONE
    leave_type: str | None = None
    punches_count: int = 0
    is_currently_in: bool = False


@router.get(
    "/daily-analysis",
    response_model=DailyAnalysisResponse,
    summary="Daily employee presence, punctuality, and attendance analysis",
    dependencies=[require_permission("people.read")],
)
async def daily_analysis(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    work_date: date | None = Query(
        default=None, description="Target calendar date (defaults to today)"
    ),
    department: str | None = Query(default=None, description="Filter by department name"),
    status: str | None = Query(default=None, description="Filter by attendance status"),
    search: str | None = Query(default=None, description="Search by employee name or number"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> DailyAnalysisResponse:
    scope = scope.for_permission("people.read")
    target_date = work_date if isinstance(work_date, date) else business_today()
    start_ts = datetime.combine(target_date - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    end_ts = datetime.combine(target_date + timedelta(days=2), datetime.min.time(), tzinfo=UTC)

    # 1. Query all active employments in scope — the caller's own company/team/self,
    #    never the whole tenant (an employee of one company must not see another's staff).
    scope_clause, scope_params = scope.employment_filter_sql("e")
    emp_query = text(f"""
        SELECT
            e.id, e.employee_number, e.legal_entity_id, a.org_unit_id,
            p.legal_first_name || ' ' || p.legal_last_name AS name,
            ua.email AS email,
            ou.name AS department,
            j.title AS designation,
            l.name AS location
        FROM employments e
        JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
        LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
        LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id AND
        (a.effective_to IS NULL OR a.effective_to > CAST(:target_date AS date)) AND
        a.effective_from <= CAST(:target_date AS date)
        LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
        LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
        LEFT JOIN locations l ON l.tenant_id = a.tenant_id AND l.id = a.location_id
        WHERE e.tenant_id = CAST(:tid AS uuid)
          AND e.hire_date <= CAST(:target_date AS date)
          AND (e.separation_date IS NULL OR e.separation_date > CAST(:target_date AS date))
          {scope_clause}
        ORDER BY p.legal_first_name ASC
    """)
    emp_rows = (
        (
            await session.execute(
                emp_query, {"tid": str(tenant_id), "target_date": target_date, **scope_params}
            )
        )
        .mappings()
        .all()
    )

    # Everything below is fetched only for the people found above — a company-scoped
    # caller must not pull (and discard) the whole tenant's day of attendance.
    emp_ids = [str(e["id"]) for e in emp_rows]

    # 2. Query attendance_days for target_date
    ad_query = text("""
        SELECT ad.employment_id, ad.status, ad.first_punch_in, ad.last_punch_out,
               ad.gross_minutes, ad.break_minutes, ad.effective_minutes,
               ad.late_by_minutes, ad.early_departure_minutes, ad.ot_minutes, ad.ot_status
        FROM attendance_days ad
        WHERE ad.tenant_id = CAST(:tid AS uuid)
          AND ad.work_date = CAST(:target_date AS date)
          AND ad.employment_id = ANY(CAST(:ids AS uuid[]))
    """)
    ad_rows = (
        (
            await session.execute(
                ad_query, {"tid": str(tenant_id), "target_date": target_date, "ids": emp_ids}
            )
        )
        .mappings()
        .all()
    )
    ad_map = {str(r["employment_id"]): r for r in ad_rows}

    # 3. Query approved leaves spanning target_date
    leave_query = text("""
        SELECT la.employment_id, lt.name AS leave_type_name
        FROM leave_applications la
        JOIN leave_types lt ON lt.tenant_id = la.tenant_id AND lt.id = la.leave_type_id
        WHERE la.tenant_id = CAST(:tid AS uuid)
          AND la.status = 'APPROVED'
          AND la.from_date <= CAST(:target_date AS date)
          AND la.to_date >= CAST(:target_date AS date)
          AND la.employment_id = ANY(CAST(:ids AS uuid[]))
    """)
    leave_rows = (
        (
            await session.execute(
                leave_query, {"tid": str(tenant_id), "target_date": target_date, "ids": emp_ids}
            )
        )
        .mappings()
        .all()
    )
    leave_map = {str(r["employment_id"]): r["leave_type_name"] for r in leave_rows}

    # 3b. Is target_date a tenant-wide holiday? (per-legal-entity holidays are
    # excluded here since this query doesn't currently resolve each
    # employee's legal entity — only the tenant-wide calendar applies.)
    holiday_row = await session.execute(
        text("""
            SELECT legal_entity_id FROM holidays
            WHERE tenant_id = CAST(:tid AS uuid) AND holiday_date = CAST(:target_date AS date)
              AND archived_at IS NULL AND is_optional = false
        """),
        {"tid": str(tenant_id), "target_date": target_date},
    )
    holiday_entities = {r[0] for r in holiday_row}

    # 4. Query punches for target_date
    punch_query = text("""
        SELECT p.id, p.original_punch_id, p.work_date, p.employment_id, p.punch_type, p.punched_at
        FROM punches p
        WHERE p.tenant_id = CAST(:tid AS uuid)
          AND (p.work_date = CAST(:target_date AS date)
               OR (p.work_date IS NULL
                   AND p.punched_at >= CAST(:start_ts AS timestamptz)
                   AND p.punched_at <= CAST(:end_ts AS timestamptz)))
          AND p.employment_id = ANY(CAST(:ids AS uuid[]))
        ORDER BY p.punched_at ASC
    """)
    punch_rows = (
        (
            await session.execute(
                punch_query,
                {
                    "tid": str(tenant_id),
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "target_date": target_date,
                    "ids": emp_ids,
                },
            )
        )
        .mappings()
        .all()
    )

    punches_by_emp: dict[str, list] = {}
    for p in punch_rows:
        punches_by_emp.setdefault(str(p["employment_id"]), []).append(p)

    records: list[_DailyRecord] = []
    hourly_counter: dict[str, int] = {f"{h:02d}:00": 0 for h in range(7, 20)}

    policies = PolicyResolver(session, tenant_id, target_date)
    for emp in emp_rows:
        emp_id = str(emp["id"])
        ad = ad_map.get(emp_id)
        leave_type = leave_map.get(emp_id)
        emp_policy = await policies.resolve(
            emp["id"], org_unit_id=emp["org_unit_id"], legal_entity_id=emp["legal_entity_id"]
        )
        all_events = punches_by_emp.get(emp_id, [])
        replaced = {p["original_punch_id"] for p in all_events if p["original_punch_id"]}
        emp_punches = [
            p
            for p in all_events
            if p["id"] not in replaced
            and p["punch_type"] != "VOID"
            and (
                p["work_date"] == target_date
                or (
                    p["work_date"] is None
                    and work_date_for(p["punched_at"], emp_policy) == target_date
                )
            )
        ]
        is_holiday = None in holiday_entities or emp["legal_entity_id"] in holiday_entities

        is_currently_in = False
        if emp_punches:
            last_punch = emp_punches[-1]
            is_currently_in = last_punch["punch_type"] in (PunchType.IN, PunchType.BREAK_END)

        first_in = (
            ad["first_punch_in"] if ad else (emp_punches[0]["punched_at"] if emp_punches else None)
        )
        last_out = (
            ad["last_punch_out"]
            if ad
            else (emp_punches[-1]["punched_at"] if len(emp_punches) > 1 else None)
        )
        effective = ad["effective_minutes"] if ad else 0
        gross = ad["gross_minutes"] if ad else 0
        brk = ad["break_minutes"] if ad else 0
        late_by = ad["late_by_minutes"] if ad else 0
        early_dep = ad["early_departure_minutes"] if ad else 0

        # Safety-net: if late_by is 0 and we have first_in and policy, compute lateness
        if first_in and late_by == 0:
            live_late = calc_lateness(
                first_in,
                emp_policy.expected_start_time,
                emp_policy.grace_late_minutes,
                emp_policy.timezone,
            )
            late_by = live_late.late_by_minutes

        if leave_type:
            status_str = "ON_LEAVE"
        elif is_holiday and not first_in:
            status_str = "HOLIDAY"
        elif ad and ad["status"] not in ("PENDING", None):
            status_str = str(ad["status"])
        elif first_in:
            status_str = "LATE" if late_by > 0 else "PRESENT"
        else:
            status_str = (
                "ABSENT"
                if is_working_day(target_date, emp_policy.work_days, emp_policy.saturday_pattern)
                else "WEEKEND"
            )

        if first_in:
            hour_str = f"{to_tz(first_in, emp_policy.timezone).hour:02d}:00"
            if hour_str in hourly_counter:
                hourly_counter[hour_str] += 1

        # Policy-driven, same as everything else here — no more hardcoded
        # flat-8-hour threshold. See core/datetime_utils.calc_overtime() and
        # apply_overtime() in time/models.py for how this got persisted.
        overtime = ad["ot_minutes"] if ad else 0
        overtime_status = ad["ot_status"] if ad else OvertimeStatus.NONE

        record = _DailyRecord(
            employment_id=emp["id"],
            employee_number=emp["employee_number"],
            name=emp["name"],
            email=emp["email"],
            department=emp["department"],
            designation=emp["designation"],
            location=emp["location"],
            status=status_str,
            first_punch_in=first_in,
            last_punch_out=last_out,
            effective_minutes=effective,
            gross_minutes=gross,
            break_minutes=brk,
            late_by_minutes=late_by,
            early_departure_minutes=early_dep,
            overtime_minutes=overtime,
            overtime_status=overtime_status,
            leave_type=leave_type,
            punches_count=len(emp_punches),
            is_currently_in=is_currently_in,
        )
        records.append(record)

    # Calculate overall metrics. Each record lands in exactly one presence bucket
    # (see time/presence.py), so present + on_leave + absent never exceeds the headcount.
    def bucket(r: _DailyRecord) -> str:
        return classify(r.status, r.first_punch_in, on_leave=r.leave_type is not None)

    total_headcount = len(records)
    present_records = [r for r in records if bucket(r) == "present"]
    present_count = len(present_records)
    late_count = len([r for r in present_records if is_late(r.status, r.late_by_minutes)])
    on_time_count = present_count - late_count
    absent_count = len([r for r in records if bucket(r) == "absent"])
    on_leave_count = len([r for r in records if bucket(r) == "on_leave"])
    half_day_count = len([r for r in records if r.status == "HALF_DAY"])
    presence_rate = (
        round((present_count / total_headcount * 100), 1) if total_headcount > 0 else 0.0
    )
    avg_minutes = (
        round(sum(r.effective_minutes for r in present_records) / present_count)
        if present_count > 0
        else 0
    )
    total_overtime = sum(r.overtime_minutes for r in records)

    # Department breakdown
    dept_map: dict[str, dict] = {}
    for r in records:
        d_name = r.department or "General"
        if d_name not in dept_map:
            dept_map[d_name] = {"total": 0, "present": 0, "late": 0, "absent": 0, "on_leave": 0}
        dept_map[d_name]["total"] += 1
        kind = bucket(r)
        if kind == "present":
            dept_map[d_name]["present"] += 1
            if is_late(r.status, r.late_by_minutes):
                dept_map[d_name]["late"] += 1
        elif kind == "absent":
            dept_map[d_name]["absent"] += 1
        elif kind == "on_leave":
            dept_map[d_name]["on_leave"] += 1

    department_stats = [
        DepartmentAttendanceStat(
            department=k,
            total=v["total"],
            present=v["present"],
            late=v["late"],
            absent=v["absent"],
            on_leave=v["on_leave"],
            presence_rate=round((v["present"] / v["total"] * 100), 1) if v["total"] > 0 else 0.0,
        )
        for k, v in sorted(dept_map.items())
    ]

    # Hourly arrivals
    hourly_arrivals = [HourlyArrivalStat(hour=h, count=c) for h, c in hourly_counter.items()]

    # Apply filters to records if requested
    filtered_records = records
    if department:
        filtered_records = [
            r
            for r in filtered_records
            if r.department and r.department.lower() == department.lower()
        ]
    if status:
        if status.upper() == "PRESENT":
            filtered_records = [r for r in filtered_records if bucket(r) == "present"]
        elif status.upper() == "LATE":
            filtered_records = [
                r
                for r in filtered_records
                if bucket(r) == "present" and is_late(r.status, r.late_by_minutes)
            ]
        else:
            filtered_records = [r for r in filtered_records if r.status.upper() == status.upper()]
    if search:
        s_lower = search.strip().lower()
        filtered_records = [
            r
            for r in filtered_records
            if s_lower in r.name.lower() or s_lower in r.employee_number.lower()
        ]

    return DailyAnalysisResponse(
        work_date=target_date,
        metrics=DailyMetrics(
            total_headcount=total_headcount,
            present_count=present_count,
            on_time_count=on_time_count,
            late_count=late_count,
            absent_count=absent_count,
            on_leave_count=on_leave_count,
            half_day_count=half_day_count,
            presence_rate=presence_rate,
            average_work_minutes=avg_minutes,
            total_overtime_minutes=total_overtime,
        ),
        department_stats=department_stats,
        hourly_arrivals=hourly_arrivals,
        total_filtered=len(filtered_records),
        employees=[
            DailyEmployeeRecord(
                **{
                    **asdict(record),
                    "employment_id": to_typed_id("employment", record.employment_id),
                }
            )
            for record in filtered_records[offset : offset + limit]
        ],
    )


def _holiday_response(h: Holiday) -> HolidayResponse:
    return HolidayResponse(
        id=to_typed_id("holiday", h.id),
        holiday_date=h.holiday_date,
        name=h.name,
        legal_entity_id=to_typed_id("legal_entity", h.legal_entity_id)
        if h.legal_entity_id
        else None,
        is_optional=h.is_optional,
    )


def _attendance_day_response(r: AttendanceDay) -> AttendanceDayResponse:
    return AttendanceDayResponse(
        id=to_typed_id("attendance_day", r.id),
        employment_id=to_typed_id("employment", r.employment_id),
        work_date=r.work_date,
        first_punch_in=r.first_punch_in,
        last_punch_out=r.last_punch_out,
        effective_minutes=r.effective_minutes,
        late_by_minutes=r.late_by_minutes,
        early_departure_minutes=r.early_departure_minutes,
        status=r.status,
        is_locked=r.is_locked,
        ot_minutes=r.ot_minutes,
        ot_status=r.ot_status,
        ot_reviewed_by=to_typed_id("employment", r.ot_reviewed_by) if r.ot_reviewed_by else None,
        ot_reviewed_at=r.ot_reviewed_at,
        ot_review_notes=r.ot_review_notes,
    )


async def _get_or_create_attendance_day(
    session, tenant_id, employment_id, work_date: date
) -> AttendanceDay:
    row = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.employment_id == employment_id)
        .where(AttendanceDay.work_date == work_date)
    )
    ad = row.scalars().first()
    if ad is None:
        ad = AttendanceDay(
            tenant_id=tenant_id,
            id=uuid4(),
            employment_id=employment_id,
            work_date=work_date,
            status=AttendanceStatus.PENDING,
            recorded_at=now_utc(),
        )
        session.add(ad)
    return ad

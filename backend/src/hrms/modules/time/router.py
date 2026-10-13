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

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import col, select

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
from hrms.core.datetime_utils import (
    business_today,
    is_working_day,
    now_utc,
    shift_lateness,
    to_tz,
)
from hrms.core.errors import CodedHTTPException
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.approvals import service as approval_flow
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.holidays import holiday_scope_sql
from hrms.modules.time.models import (
    LONG_DAY_MINUTES,
    AttendanceDay,
    AttendanceStatus,
    Holiday,
    HolidayCalendar,
    HolidayCalendarDay,
    OvertimeStatus,
    Punch,
    PunchSource,
    PunchType,
)
from hrms.modules.time.schemas import (
    AttendanceDayResponse,
    DailyAnalysisResponse,
    HolidayCreate,
    HolidayResponse,
    OvertimeReviewRequest,
    PendingOvertimeItem,
    PunchCreate,
    PunchResponse,
    TodayStatusResponse,
)
from hrms.modules.time.service import (
    carried_over_day,
    events_for_day,
    is_live_punched_in,
    lock_day,
    recompute_day,
    stale_open_day,
    work_date_for,
)

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
    previous_policy = await resolve_policy(emp_uuid, day - timedelta(days=1), session, tenant_id)
    if body.punch_type != PunchType.IN:
        # Checking out (or breaking) after midnight ends the session that is still open,
        # up to 24 hours after it began.
        carried = await carried_over_day(
            session, tenant_id, emp_uuid, day, policy, previous_policy, punched_at
        )
        if carried is not None:
            day, policy = carried, previous_policy
        elif not await events_for_day(session, tenant_id, emp_uuid, day, policy):
            stale = await stale_open_day(
                session, tenant_id, emp_uuid, day, previous_policy, punched_at
            )
            if stale is not None:
                raise HTTPException(
                    409,
                    f"Missed punch: your check-in on {stale:%d %b %Y} has no check-out within "
                    "24 hours. Ask HR to correct it, then check in for today.",
                )
    else:
        # Checking in on a new day: a session left open for over 24 hours is a missed punch.
        stale = await stale_open_day(session, tenant_id, emp_uuid, day, previous_policy, punched_at)
        if stale is not None:
            await recompute_day(session, tenant_id, emp_uuid, stale, previous_policy)
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
    opened = min((e.punched_at for e in events if e.punch_type == "IN"), default=None)
    if (
        body.punch_type == PunchType.OUT
        and not body.confirm_long_day
        and opened is not None
        and punched_at - opened > timedelta(minutes=LONG_DAY_MINUTES)
    ):
        # Usually a check-in left open overnight. Recording it as worked time needs the
        # employee to say so; the day then goes to HR to check before any overtime counts.
        hours = int((punched_at - opened).total_seconds() // 3600)
        raise CodedHTTPException(
            409,
            f"You checked in at {to_tz(opened, policy.timezone):%I:%M %p on %d %b} and haven't "
            f"checked out since. Checking out now records a {hours}-hour day, which HR will "
            "review. If you forgot to check out, ask HR to correct the time instead.",
            code="LONG_DAY_CONFIRM",
        )
    punch = Punch(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        punch_type=body.punch_type,
        punched_at=punched_at,
        work_date=day,
        # Through a connected app's employee session the source is the app, whatever the body
        # says, so an app can't pass its punches off as web or device punches.
        source=PunchSource.INTEGRATION if principal.via_key_id else body.source,
        source_system=principal.via_app if principal.via_key_id else None,
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
    now = now_utc()
    policy = await resolve_policy(emp_uuid, now.date(), session, tenant_id)
    target_date = work_date if isinstance(work_date, date) else work_date_for(now, policy)
    policy = await resolve_policy(emp_uuid, target_date, session, tenant_id)
    # Display only this work date. A forgotten check-out on a previous work date
    # must not make the employee appear checked in today. Overnight shifts are
    # already assigned their correct work date by work_date_for().
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
    if not isinstance(work_date, date):
        is_punched_in = is_live_punched_in(punches, now)

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
    rows = list((await session.execute(q.order_by(col(Holiday.holiday_date)))).scalars())
    calendar_rows = await session.execute(
        select(HolidayCalendar).where(
            HolidayCalendar.tenant_id == tenant_id,
            HolidayCalendar.archived_at == None,  # noqa: E711
        )
    )
    calendars = {c.id: c.name for c in calendar_rows.scalars()}
    # A holiday is one row however many calendars observe it: name every live calendar it is
    # on. One that is only on archived calendars went with them and isn't listed.
    on: dict = {}
    on_any_calendar = set()
    for d in (
        await session.execute(
            select(HolidayCalendarDay).where(HolidayCalendarDay.tenant_id == tenant_id)
        )
    ).scalars():
        on_any_calendar.add(d.holiday_id)
        if d.calendar_id in calendars:
            on.setdefault(d.holiday_id, set()).add(calendars[d.calendar_id])
    for h in rows:
        if h.calendar_id:
            on_any_calendar.add(h.id)
            if h.calendar_id in calendars:
                on.setdefault(h.id, set()).add(calendars[h.calendar_id])
    return [
        _holiday_response(h, ", ".join(sorted(on[h.id])) if h.id in on else None)
        for h in rows
        if h.id in on or h.id not in on_any_calendar
    ]


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
    # Removing a holiday takes it off every calendar that observed it.
    for d in (
        await session.execute(
            select(HolidayCalendarDay).where(
                HolidayCalendarDay.tenant_id == tenant_id, HolidayCalendarDay.holiday_id == h.id
            )
        )
    ).scalars():
        await session.delete(d)
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


# ─── Days flagged for review ──────────────────────────────────────────────────
#
# A day is flagged when a break was never ended or it ran over 16 hours. Its overtime and
# comp-off are held until someone who approves corrections either corrects the punches (the
# flag clears itself) or marks the day reviewed — accepting the time as worked.


@router.post(
    "/attendance-days/{attendance_day_id}/review",
    response_model=AttendanceDayResponse,
    summary="Accept a flagged attendance day as recorded",
    dependencies=[require_permission("corrections.approve")],
)
async def review_attendance_day(
    attendance_day_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> AttendanceDayResponse:
    ad = (
        (
            await session.execute(
                select(AttendanceDay)
                .where(AttendanceDay.tenant_id == tenant_id)
                .where(AttendanceDay.id == to_uuid(attendance_day_id))
            )
        )
        .scalars()
        .first()
    )
    if not ad:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attendance day not found")
    await authorize_employment(
        session, tenant_id, scope.for_permission("corrections.approve"), ad.employment_id
    )
    if ad.employment_id == principal.employment_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't review your own attendance")
    ad = await lock_day(session, tenant_id, ad.employment_id, ad.work_date)
    if not ad.review_flags:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This day has nothing to review")
    if ad.reviewed_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This day has already been reviewed")
    ad.reviewed_by = principal.user_account_id
    ad.reviewed_at = now_utc()
    policy = await resolve_policy(ad.employment_id, ad.work_date, session, tenant_id)
    ad = await recompute_day(session, tenant_id, ad.employment_id, ad.work_date, policy, ad)
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
    comp_off_days: float = 0
    review_flags: list[str] = field(default_factory=list)
    needs_review: bool = False
    attendance_day_id: str | None = None
    leave_type: str | None = None
    punches_count: int = 0
    is_currently_in: bool = False


async def _daily_batch(session, tenant_id, scope, target_date, batch_offset, policies):
    start_ts = datetime.combine(target_date - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    end_ts = datetime.combine(target_date + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
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
        ORDER BY p.legal_first_name ASC, e.id ASC
        LIMIT 250 OFFSET :batch_offset
    """)
    emp_rows = (
        (
            await session.execute(
                emp_query,
                {
                    "tid": str(tenant_id),
                    "target_date": target_date,
                    "batch_offset": batch_offset,
                    **scope_params,
                },
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
        SELECT ad.id, ad.employment_id, ad.status, ad.first_punch_in, ad.last_punch_out,
               ad.gross_minutes, ad.break_minutes, ad.effective_minutes,
               ad.late_by_minutes, ad.early_departure_minutes, ad.ot_minutes, ad.ot_status,
               ad.comp_off_days, ad.review_flags, ad.reviewed_at
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

    # Calendars follow dated employee assignments; legacy holidays keep company scope.
    holiday_row = await session.execute(
        text(f"""
            SELECT DISTINCT e.id FROM employments e JOIN holidays h
              ON h.tenant_id = e.tenant_id
            WHERE h.tenant_id = CAST(:tid AS uuid)
              AND h.holiday_date = CAST(:target_date AS date)
              AND h.archived_at IS NULL AND h.is_optional = false
              AND e.id = ANY(CAST(:ids AS uuid[]))
              AND {holiday_scope_sql(employee="e.id")}
        """),
        {"tid": str(tenant_id), "target_date": target_date, "ids": emp_ids},
    )
    holiday_employees = {str(r[0]) for r in holiday_row}

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
        is_holiday = emp_id in holiday_employees

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

        # Only when no attendance day has been computed yet (punches without a recompute):
        # estimate lateness from the first punch, rounded as the policy rounds. A stored day
        # is authoritative — recomputing from the raw punch here ignored rounding and made
        # this screen disagree with every other report.
        if first_in and ad is None:
            live_late = shift_lateness(
                first_in,
                emp_policy.expected_start_time,
                emp_policy.expected_end_time,
                emp_policy.grace_late_minutes,
                emp_policy.timezone,
                emp_policy.punch_rounding_minutes,
                emp_policy.punch_rounding_direction,
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
        review_flags = ad["review_flags"].split(",") if ad and ad["review_flags"] else []

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
            comp_off_days=ad["comp_off_days"] if ad else 0,
            review_flags=review_flags,
            needs_review=bool(review_flags) and ad is not None and ad["reviewed_at"] is None,
            attendance_day_id=to_typed_id("attendance_day", ad["id"]) if ad else None,
            leave_type=leave_type,
            punches_count=len(emp_punches),
            is_currently_in=is_currently_in,
        )
        records.append(record)

    return records, hourly_counter, len(emp_rows)


@router.get(
    "/daily-analysis",
    response_model=DailyAnalysisResponse,
    dependencies=[require_permission("people.read")],
)
async def daily_analysis(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    work_date: date | None = Query(default=None),
    department: str | None = Query(default=None, max_length=255),
    status: str | None = Query(default=None, max_length=30),
    search: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    snapshot_id: UUID | None = Query(default=None),
) -> DailyAnalysisResponse:
    from hrms.modules.time.snapshots import read_snapshot

    return await read_snapshot(
        session,
        tenant_id,
        principal.user_account_id,
        scope.for_permission("people.read"),
        work_date if isinstance(work_date, date) else business_today(),
        department,
        status,
        search,
        limit,
        offset,
        snapshot_id,
        _daily_batch,
    )


@router.get("/daily-analysis/export", dependencies=[require_permission("people.read")])
async def daily_analysis_export(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    snapshot_id: UUID,
    work_date: date,
    department: str | None = Query(default=None, max_length=255),
    status: str | None = Query(default=None, max_length=30),
    search: str | None = Query(default=None, max_length=255),
):
    from hrms.modules.time.snapshots import export_snapshot

    return await export_snapshot(
        session,
        tenant_id,
        principal.user_account_id,
        scope.for_permission("people.read"),
        work_date,
        department,
        status,
        search,
        snapshot_id,
    )


def _holiday_response(h: Holiday, calendar_name: str | None = None) -> HolidayResponse:
    return HolidayResponse(
        id=to_typed_id("holiday", h.id),
        holiday_date=h.holiday_date,
        name=h.name,
        legal_entity_id=to_typed_id("legal_entity", h.legal_entity_id)
        if h.legal_entity_id
        else None,
        is_optional=h.is_optional,
        calendar_id=to_typed_id("holiday_calendar", h.calendar_id) if h.calendar_id else None,
        calendar_name=calendar_name,
        holiday_type=h.holiday_type,
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
        comp_off_days=r.comp_off_days,
        review_flags=r.review_flags.split(",") if r.review_flags else [],
        needs_review=bool(r.review_flags) and r.reviewed_at is None,
        reviewed_by=to_typed_id("user", r.reviewed_by) if r.reviewed_by else None,
        reviewed_at=r.reviewed_at,
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

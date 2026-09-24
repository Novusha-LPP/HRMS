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

from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, Query
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, resolve_acting_employment_id
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import compute_day, now_utc
from hrms.core.ids import to_typed_id
from hrms.core.tenancy import TenantDep
from hrms.modules.policy.engine import resolve_policy
from hrms.modules.time.models import (
    AttendanceDay,
    AttendanceStatus,
    Punch,
    PunchType,
)
from hrms.modules.time.schemas import (
    AttendanceDayResponse,
    PunchCreate,
    PunchResponse,
    TodayStatusResponse,
)

router = APIRouter(prefix="/v1/time", tags=["Time & Attendance"])


@router.post("/punches", response_model=PunchResponse, status_code=201,
             summary="Record a punch (in or out)")
async def create_punch(
    body: PunchCreate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id_header: str | None = Query(
        default=None, alias="employment-id",
        description="Typed employment ID (emp_...). Defaults to your own.",
    ),
) -> PunchResponse:
    emp_uuid = resolve_acting_employment_id(principal, employment_id_header)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    uid = uuid4()
    punched_at = body.punched_at or now_utc()

    punch = Punch(
        tenant_id=tenant_id,
        id=uid,
        employment_id=emp_uuid,
        punch_type=body.punch_type,
        punched_at=punched_at,
        source=body.source,
        latitude=body.latitude,
        longitude=body.longitude,
        device_id=body.device_id,
        recorded_at=now_utc(),
    )
    session.add(punch)

    today = punched_at.date()
    ad = await _get_or_create_attendance_day(session, tenant_id, emp_uuid, today)

    if body.punch_type == PunchType.IN:
        if ad.first_punch_in is None:
            ad.first_punch_in = punched_at
        ad.status = AttendanceStatus.PRESENT
    elif body.punch_type == PunchType.OUT:
        ad.last_punch_out = punched_at
        if ad.first_punch_in:
            policy = await resolve_policy(emp_uuid, today, session, tenant_id)
            result = compute_day(
                punch_in=ad.first_punch_in,
                punch_out=punched_at,
                break_minutes=policy.break_minutes,
                expected_start=policy.expected_start_time,
                expected_end=policy.expected_end_time,
                grace_late_minutes=policy.grace_late_minutes,
                grace_early_departure_minutes=policy.grace_early_departure_minutes,
                half_day_threshold_pct=policy.half_day_threshold_pct,
                ot_enabled=policy.ot_enabled,
                ot_qualifying_minutes=policy.ot_qualifying_minutes,
                ot_daily_cap_minutes=policy.ot_daily_cap_minutes,
                tz_name=policy.timezone,
                punch_rounding_minutes=policy.punch_rounding_minutes,
                punch_rounding_direction=policy.punch_rounding_direction,
                break_auto_deduct=policy.break_auto_deduct,
            )
            ad.gross_minutes = result.gross_minutes
            ad.break_minutes = result.break_minutes
            ad.effective_minutes = result.effective_minutes
            ad.late_by_minutes = result.late_by_minutes
            ad.early_departure_minutes = result.early_departure_minutes
            ad.status = getattr(AttendanceStatus, result.status, AttendanceStatus.PRESENT)

    session.add(ad)
    await session.flush()

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


@router.get("/today", response_model=TodayStatusResponse,
            summary="Today's punch status for an employee")
async def today_status(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
) -> TodayStatusResponse:
    emp_uuid = resolve_acting_employment_id(principal, employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    today = date.today()

    ad_row = await session.execute(
        select(AttendanceDay)
        .where(AttendanceDay.tenant_id == tenant_id)
        .where(AttendanceDay.employment_id == emp_uuid)
        .where(AttendanceDay.work_date == today)
    )
    ad = ad_row.scalars().first()

    punches_row = await session.execute(
        select(Punch)
        .where(Punch.tenant_id == tenant_id)
        .where(Punch.employment_id == emp_uuid)
        .where(Punch.punched_at >= datetime.combine(today, datetime.min.time()))
        .order_by(Punch.punched_at)  # type: ignore[attr-defined]
    )
    punches = list(punches_row.scalars())

    is_punched_in = False
    if punches:
        last = punches[-1]
        is_punched_in = last.punch_type in (PunchType.IN, PunchType.BREAK_END)

    return TodayStatusResponse(
        employment_id=to_typed_id("employment", emp_uuid),
        work_date=today,
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


@router.get("/attendance-days", response_model=list[AttendanceDayResponse],
            summary="Attendance days for an employee in a date range")
async def list_attendance_days(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    from_date: date = Query(...),
    to_date: date = Query(...),
    employment_id: str | None = Query(default=None, description="Defaults to your own employment"),
) -> list[AttendanceDayResponse]:
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
    return [
        AttendanceDayResponse(
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
        )
        for r in rows.scalars()
    ]


async def _get_or_create_attendance_day(session, tenant_id, employment_id, work_date: date) -> AttendanceDay:
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

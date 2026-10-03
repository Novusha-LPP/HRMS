"""One attendance event stream and recomputation path for punches and corrections."""

from datetime import UTC, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlmodel import select

from hrms.core.datetime_utils import (
    apply_punch_rounding,
    calc_lateness,
    calc_overtime,
    compute_day,
    compute_standard_minutes,
    derive_attendance_status,
    localize_date,
    now_utc,
    to_tz,
)
from hrms.core.locking import lock_resource
from hrms.modules.time.models import AttendanceDay, Punch, apply_overtime


def overnight_boundary(policy):
    start = policy.expected_start_time.hour * 60 + policy.expected_start_time.minute
    end = policy.expected_end_time.hour * 60 + policy.expected_end_time.minute
    return (start + end) // 2


def work_date_for(instant, policy):
    local = to_tz(instant, policy.timezone)
    day = local.date()
    if (
        policy.expected_end_time <= policy.expected_start_time
        and local.hour * 60 + local.minute < overnight_boundary(policy)
    ):
        day -= timedelta(days=1)
    return day


def work_bounds(day, policy):
    start = localize_date(day, policy.timezone)
    if policy.expected_end_time <= policy.expected_start_time:
        start += timedelta(minutes=overnight_boundary(policy))
    return start, start + timedelta(days=1)


async def lock_day(session, tenant_id, employment_id, day):
    await lock_resource(session, tenant_id, f"attendance:{employment_id}:{day}")
    row = (
        (
            await session.execute(
                select(AttendanceDay)
                .where(AttendanceDay.tenant_id == tenant_id)
                .where(AttendanceDay.employment_id == employment_id)
                .where(AttendanceDay.work_date == day)
                .with_for_update()
            )
        )
        .scalars()
        .first()
    )
    if row and row.is_locked:
        raise HTTPException(409, "This attendance period is locked")
    return row


async def events_for_day(session, tenant_id, employment_id, day, policy):
    start, end = work_bounds(day, policy)
    events = list(
        (
            await session.execute(
                select(Punch)
                .where(Punch.tenant_id == tenant_id)
                .where(Punch.employment_id == employment_id)
                .where(
                    or_(
                        Punch.work_date == day,
                        and_(
                            Punch.work_date.is_(None),
                            Punch.punched_at >= start,
                            Punch.punched_at < end,
                        ),
                    )
                )
                .order_by(Punch.punched_at, Punch.recorded_at)
            )
        ).scalars()
    )
    replaced = {e.original_punch_id for e in events if e.original_punch_id}
    return [e for e in events if e.id not in replaced and e.punch_type != "VOID"]


def event_minutes(events, rounding_minutes=0, rounding_direction="NONE"):
    """Pair sessions and explicit breaks; incomplete sessions contribute no duration."""
    started = None
    break_start = None
    duration = 0
    breaks = 0
    session_breaks = 0
    for event in events:
        stamp = apply_punch_rounding(
            event.punched_at, rounding_minutes, rounding_direction
        ).astimezone(UTC)
        if event.punch_type == "IN":
            if started is not None:
                raise HTTPException(422, "Consecutive IN events need correction")
            started = stamp
            session_breaks = 0
        elif event.punch_type == "BREAK_START":
            if started is None or break_start is not None:
                raise HTTPException(422, "Break must start during an open session")
            break_start = stamp
        elif event.punch_type == "BREAK_END":
            if break_start is None:
                raise HTTPException(422, "No open break to end")
            session_breaks += int((stamp - break_start).total_seconds() / 60)
            break_start = None
        elif event.punch_type == "OUT":
            if started is None:
                # An incomplete historical OUT can be repaired with a missing IN.
                continue
            if break_start is not None:
                session_breaks += int((stamp - break_start).total_seconds() / 60)
                break_start = None
            session_duration = max(0, int((stamp - started).total_seconds() / 60))
            duration += session_duration
            breaks += min(session_duration, session_breaks)
            session_breaks = 0
            started = None
    return max(0, duration), max(0, breaks), started is not None


async def recompute_day(session, tenant_id, employment_id, day, policy, ad=None):
    ad = ad or await lock_day(session, tenant_id, employment_id, day)
    ad = ad or AttendanceDay(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=employment_id,
        work_date=day,
        recorded_at=now_utc(),
    )
    events = await events_for_day(session, tenant_id, employment_id, day, policy)
    ins = [e.punched_at for e in events if e.punch_type == "IN"]
    outs = [e.punched_at for e in events if e.punch_type == "OUT"]
    ad.first_punch_in = min(ins) if ins else None
    ad.last_punch_out = max(outs) if outs else None
    ad.gross_minutes = ad.break_minutes = ad.effective_minutes = 0
    ad.late_by_minutes = ad.early_departure_minutes = 0

    # Calculate lateness immediately upon first check-in
    if ad.first_punch_in:
        late_res = calc_lateness(
            ad.first_punch_in,
            policy.expected_start_time,
            policy.grace_late_minutes,
            policy.timezone,
        )
        ad.late_by_minutes = late_res.late_by_minutes
        ad.status = "LATE" if late_res.is_late else "PRESENT"
    else:
        ad.status = "ABSENT"

    duration, breaks, open_session = event_minutes(
        events, policy.punch_rounding_minutes, policy.punch_rounding_direction
    )
    ot = 0
    if ins and outs and ad.last_punch_out >= ad.first_punch_in:
        result = compute_day(
            ad.first_punch_in,
            ad.last_punch_out,
            policy.break_minutes,
            policy.expected_start_time,
            policy.expected_end_time,
            policy.grace_late_minutes,
            policy.grace_early_departure_minutes,
            policy.half_day_threshold_pct,
            policy.ot_enabled,
            policy.ot_qualifying_minutes,
            policy.ot_daily_cap_minutes,
            policy.timezone,
            policy.punch_rounding_minutes,
            policy.punch_rounding_direction,
            policy.break_auto_deduct,
        )
        # Use paired sessions rather than counting time between separate visits as work.
        deducted = (
            breaks
            if any(e.punch_type.startswith("BREAK_") for e in events)
            else (policy.break_minutes if policy.break_auto_deduct else 0)
        )
        ad.gross_minutes = duration
        ad.break_minutes = min(duration, deducted)
        ad.effective_minutes = max(0, duration - deducted)
        ad.late_by_minutes = result.late_by_minutes
        ad.early_departure_minutes = result.early_departure_minutes
        standard = compute_standard_minutes(
            policy.expected_start_time, policy.expected_end_time, policy.break_minutes
        )
        ad.status = (
            ("LATE" if result.is_late else "PRESENT")
            if open_session
            else derive_attendance_status(
                True,
                ad.effective_minutes,
                standard,
                policy.half_day_threshold_pct,
                result.is_late,
                result.is_early_departure,
            )
        )
        if not open_session:
            ot = calc_overtime(
                ad.effective_minutes,
                standard,
                policy.ot_enabled,
                policy.ot_qualifying_minutes,
                policy.ot_daily_cap_minutes,
            ).ot_minutes
    apply_overtime(ad, ot)
    session.add(ad)
    await session.flush()
    return ad

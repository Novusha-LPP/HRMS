"""One attendance event stream and recomputation path for punches and corrections."""

from datetime import UTC, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, text
from sqlmodel import col, select

from hrms.core.datetime_utils import (
    apply_punch_rounding,
    calc_overtime,
    compute_day,
    compute_standard_minutes,
    derive_attendance_status,
    is_working_day,
    localize_date,
    now_utc,
    shift_lateness,
    to_tz,
)
from hrms.core.locking import lock_resource
from hrms.modules.approvals import service as approval_flow
from hrms.modules.leave.comp_off import earned_comp_off, sync_attendance_comp_off
from hrms.modules.time.holidays import holiday_scope_sql
from hrms.modules.time.models import (
    LONG_DAY_MINUTES,
    AttendanceDay,
    AttendanceStatus,
    OvertimeStatus,
    Punch,
    ReviewFlag,
    apply_overtime,
)


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


# How long a session can stay open: within this a check-out on the next date still ends it;
# after it the check-out is refused and the day is flagged MISSED_PUNCH.
MAX_OPEN_SESSION = timedelta(hours=24)
OPEN_EVENTS = ("IN", "BREAK_START", "BREAK_END")


def is_live_punched_in(events, instant):
    """A live clock expires from the latest check-in, never from a later break event."""
    if not events or events[-1].punch_type not in ("IN", "BREAK_END"):
        return False
    opened = max((e.punched_at for e in events if e.punch_type == "IN"), default=None)
    return (
        opened is not None
        and events[-1].punched_at <= instant
        and timedelta(0) <= instant - opened <= MAX_OPEN_SESSION
    )


async def carried_over_day(
    session, tenant_id, employment_id, day, policy, previous_policy, instant
):
    """
    The previous work date, when `instant` falls on a date with no punches yet while the
    previous date's session is still open and began at most MAX_OPEN_SESSION ago — e.g.
    checking out at 01:15 after a day that started at 09:30. Otherwise None.
    """
    if await events_for_day(session, tenant_id, employment_id, day, policy):
        return None
    previous = day - timedelta(days=1)
    events = await events_for_day(session, tenant_id, employment_id, previous, previous_policy)
    if not events or events[-1].punch_type not in OPEN_EVENTS:
        return None
    opened = max(e.punched_at for e in events if e.punch_type == "IN")
    return previous if timedelta(0) <= instant - opened <= MAX_OPEN_SESSION else None


async def stale_open_day(session, tenant_id, employment_id, day, previous_policy, instant):
    """
    The previous work date when its session is still open and began more than
    MAX_OPEN_SESSION before `instant` — a missed check-out. Otherwise None.
    """
    previous = day - timedelta(days=1)
    events = await events_for_day(session, tenant_id, employment_id, previous, previous_policy)
    if not events or events[-1].punch_type not in OPEN_EVENTS:
        return None
    opened = max(e.punched_at for e in events if e.punch_type == "IN")
    return previous if instant - opened > MAX_OPEN_SESSION else None


async def is_off_day(session, tenant_id, employment_id, day, policy) -> bool:
    """A weekly off under the policy, or a (non-optional) holiday for the employee's company."""
    if not is_working_day(day, policy.work_days, policy.saturday_pattern):
        return True
    holiday = await session.execute(
        text(f"""
            SELECT 1 FROM holidays h
            WHERE tenant_id = :tid AND holiday_date = :day
              AND archived_at IS NULL AND is_optional = false
              AND {holiday_scope_sql()}
            LIMIT 1
        """),
        {"tid": tenant_id, "eid": employment_id, "day": day},
    )
    return holiday.first() is not None


def unended_break(events) -> bool:
    """A break was started and the next punch was a check-out, not a break end."""
    on_break = False
    for event in events:
        if event.punch_type == "BREAK_START":
            on_break = True
        elif event.punch_type in ("BREAK_END", "IN"):
            on_break = False
        elif event.punch_type == "OUT" and on_break:
            return True
    return False


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
                            col(Punch.work_date).is_(None),
                            Punch.punched_at >= start,
                            Punch.punched_at < end,
                        ),
                    )
                )
                .order_by(col(Punch.punched_at), col(Punch.recorded_at))
            )
        ).scalars()
    )
    replaced = {e.original_punch_id for e in events if e.original_punch_id}
    return [e for e in events if e.id not in replaced and e.punch_type != "VOID"]


def event_minutes(
    events, rounding_minutes=0, rounding_direction="NONE", tz_name=None, unended_break_cap=None
):
    """
    Pair sessions and explicit breaks; incomplete sessions contribute no duration.

    Returns (worked, explicit breaks, open session, span): `worked` is the sum of the paired
    IN→OUT sessions, `span` the time from the first IN to the last OUT. Their difference is
    the time actually spent checked out in between (a lunch taken by punching out, a visit
    elsewhere); nothing else is deducted.

    A break still open at check-out counts up to `unended_break_cap` minutes (the policy
    break) when given; the rest of it is worked time.
    """
    started = None
    break_start = None
    first_in = None
    last_out = None
    duration = 0
    breaks = 0
    session_breaks = 0
    for event in events:
        stamp = apply_punch_rounding(
            event.punched_at, rounding_minutes, rounding_direction, tz_name
        ).astimezone(UTC)
        if event.punch_type == "IN":
            if started is not None:
                raise HTTPException(422, "Consecutive IN events need correction")
            started = stamp
            first_in = first_in or stamp
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
                unended = int((stamp - break_start).total_seconds() / 60)
                if unended_break_cap is not None:
                    unended = min(unended, unended_break_cap)
                session_breaks += unended
                break_start = None
            session_duration = max(0, int((stamp - started).total_seconds() / 60))
            duration += session_duration
            breaks += min(session_duration, session_breaks)
            session_breaks = 0
            started = None
            last_out = stamp
    span = max(0, int((last_out - first_in).total_seconds() / 60)) if first_in and last_out else 0
    return max(0, duration), max(0, breaks), started is not None, span


async def recompute_day(
    session, tenant_id, employment_id, day, policy, ad=None, *, clear_override=False
):
    """Recalculate a day from its punches. `clear_override` is for edits by a person: what they
    recorded replaces any status carried over from another system."""
    ad = ad or await lock_day(session, tenant_id, employment_id, day)
    ad = ad or AttendanceDay(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=employment_id,
        work_date=day,
        recorded_at=now_utc(),
    )
    if clear_override:
        ad.status_override = ad.override_note = None
    events = await events_for_day(session, tenant_id, employment_id, day, policy)
    ins = [e.punched_at for e in events if e.punch_type == "IN"]
    outs = [e.punched_at for e in events if e.punch_type == "OUT"]
    off_day = bool(ins) and await is_off_day(session, tenant_id, employment_id, day, policy)
    ad.first_punch_in = min(ins) if ins else None
    ad.last_punch_out = max(outs) if outs else None
    ad.gross_minutes = ad.break_minutes = ad.effective_minutes = 0
    ad.late_by_minutes = ad.early_departure_minutes = 0

    # Lateness from the first check-in, judged the same way before and after check-out
    # (rounded as the policy rounds; night shifts against the shift that began the evening before).
    if ad.first_punch_in:
        late_res = shift_lateness(
            ad.first_punch_in,
            policy.expected_start_time,
            policy.expected_end_time,
            policy.grace_late_minutes,
            policy.timezone,
            policy.punch_rounding_minutes,
            policy.punch_rounding_direction,
        )
        ad.late_by_minutes = late_res.late_by_minutes
        ad.status = "LATE" if late_res.is_late else "PRESENT"
    else:
        ad.status = "ABSENT"

    # A break never ended counts only up to the policy break; the day goes to HR to check.
    duration, breaks, open_session, span = event_minutes(
        events,
        policy.punch_rounding_minutes,
        policy.punch_rounding_direction,
        policy.timezone,
        unended_break_cap=policy.break_minutes,
    )
    ot = 0
    comp_off = 0.0
    standard = compute_standard_minutes(
        policy.expected_start_time, policy.expected_end_time, policy.break_minutes
    )
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
        # Total runs from the first check-in to the last check-out. What is deducted is only the
        # time actually spent away — checked out between sessions, or on a recorded break —
        # so a day without a check-out in between counts in full. No break is deducted
        # automatically.
        ad.effective_minutes = max(0, duration - breaks)
        ad.gross_minutes = max(span, ad.effective_minutes)
        ad.break_minutes = ad.gross_minutes - ad.effective_minutes
        ad.late_by_minutes = result.late_by_minutes
        # Still checked in (back from lunch, say): nobody has left early yet.
        ad.early_departure_minutes = 0 if open_session else result.early_departure_minutes
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
            # Overtime starts only after the full shift (09:30-18:30 is 9 h): working the shift
            # without a break is not overtime. With an overtime policy its rules apply and the
            # minutes go for approval (and later payroll); without one the extra time is only
            # shown (INFO), never approved or paid.
            shift = compute_standard_minutes(
                policy.expected_start_time, policy.expected_end_time, 0
            )
            ot = overtime_beyond(ad.effective_minutes, shift, policy)
    if off_day:
        # A weekly off or holiday has no shift to be late or early for. What the work earns
        # follows the policy: every minute as overtime, or a comp-off day credited to leave.
        ad.status = AttendanceStatus.OFF_DAY_WORKED
        ad.late_by_minutes = ad.early_departure_minutes = 0
        ot = 0
        if outs and not open_session:
            if policy.off_day_work == "COMP_OFF":
                comp_off = earned_comp_off(
                    ad.effective_minutes, standard, policy.half_day_threshold_pct
                )
            else:
                ot = overtime_beyond(ad.effective_minutes, 0, policy)
    if open_session and ins and now_utc() - max(ins) > MAX_OPEN_SESSION:
        # Still checked in a full day later: the check-out was missed. HR corrects it.
        ad.status = "MISSED_PUNCH"
        ot = 0
        comp_off = 0.0

    if ad.status_override:
        # Carried over from another system. Rewards computed from punches that the other
        # system did not count (an off-day assumption it did not share) are not granted.
        ad.status = ad.status_override
        if ad.status_override != AttendanceStatus.OFF_DAY_WORKED:
            ot = 0
            comp_off = 0.0

    flags = []
    if not open_session and unended_break(events):
        flags.append(ReviewFlag.BREAK_NOT_ENDED)
    if ad.gross_minutes > LONG_DAY_MINUTES:
        flags.append(ReviewFlag.LONG_DAY)
    review_flags = ",".join(flags) or None
    if review_flags != ad.review_flags:
        # Different reasons (or none any more): any earlier review no longer applies.
        ad.review_flags = review_flags
        ad.reviewed_by = ad.reviewed_at = None
    if ad.review_flags and ad.reviewed_at is None:
        # Held until HR has checked the day: nothing is raised for approval or credited.
        ot = 0
        comp_off = 0.0

    payable = policy.ot_enabled
    previous_ot = ad.ot_minutes if ad.ot_status != OvertimeStatus.INFO else 0
    previous_comp_off = ad.comp_off_days or 0.0
    apply_overtime(ad, ot, payable=payable)
    ad.comp_off_days = comp_off
    session.add(ad)
    await session.flush()
    if previous_comp_off != comp_off:
        await sync_attendance_comp_off(session, tenant_id, employment_id, day, comp_off)
    ot = ot if payable else 0  # only payable overtime goes through approval
    if previous_ot != ot:
        await approval_flow.finish(
            session, tenant_id, "OVERTIME", ad.id, "SUPERSEDED" if ot else "CANCELLED"
        )
        if ot:
            await approval_flow.start(
                session,
                tenant_id,
                "OVERTIME",
                ad.id,
                employment_id,
                request_snapshot=dict(
                    work_date=day.isoformat(),
                    first_punch_in=ad.first_punch_in.isoformat() if ad.first_punch_in else None,
                    last_punch_out=ad.last_punch_out.isoformat() if ad.last_punch_out else None,
                    effective_minutes=ad.effective_minutes,
                    ot_minutes=ad.ot_minutes,
                ),
            )
    return ad


def overtime_beyond(worked, baseline, policy):
    """Minutes worked past `baseline`: under the overtime policy's rules, or plain when off."""
    if policy.ot_enabled:
        return calc_overtime(
            worked, baseline, True, policy.ot_qualifying_minutes, policy.ot_daily_cap_minutes
        ).ot_minutes
    return max(0, worked - baseline)

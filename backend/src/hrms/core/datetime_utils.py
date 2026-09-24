"""
Centralized date/time utilities for HRMS.

All datetime arithmetic and timezone conversions must go through this module to
ensure consistent, policy-driven calculations with no hard-coded rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = ZoneInfo("UTC")


def now_utc() -> datetime:
    """Current UTC time (tz-aware)."""
    return datetime.now(UTC)


def safe_tz(tz_name: str) -> ZoneInfo:
    """Return ZoneInfo for tz_name, falling back to UTC on unknown zone."""
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return UTC


def to_tz(dt: datetime, tz_name: str) -> datetime:
    """Convert UTC datetime to the given timezone."""
    tz = safe_tz(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def to_utc(dt: datetime, tz_name: str) -> datetime:
    """Interpret a naive datetime as being in tz_name, then convert to UTC."""
    tz = safe_tz(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(UTC)


def localize_date(d: date, tz_name: str) -> datetime:
    """Return midnight of date d in the given timezone (tz-aware)."""
    tz = safe_tz(tz_name)
    return datetime(d.year, d.month, d.day, tzinfo=tz)


def apply_punch_rounding(dt: datetime, rounding_minutes: int, direction: str) -> datetime:
    """
    Round punch time to the nearest rounding_minutes interval.

    direction: NONE | UP | DOWN | NEAREST
    """
    if rounding_minutes <= 0 or direction == "NONE":
        return dt
    total_secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    interval = rounding_minutes * 60
    remainder = total_secs % interval
    if direction == "UP":
        delta_secs = (interval - remainder) if remainder else 0
    elif direction == "DOWN":
        delta_secs = -remainder
    else:  # NEAREST
        delta_secs = (interval - remainder) if remainder >= interval / 2 else -remainder
    return (dt + timedelta(seconds=delta_secs)).replace(second=0, microsecond=0)


# ─── Calculation results ───────────────────────────────────────────────────────

class LatenessResult(NamedTuple):
    is_late: bool
    late_by_minutes: int


class EarlyDepartureResult(NamedTuple):
    is_early: bool
    early_by_minutes: int


class OvertimeResult(NamedTuple):
    ot_minutes: int
    qualifies: bool


@dataclass
class DayComputeResult:
    gross_minutes: int
    break_minutes: int
    effective_minutes: int
    ot_minutes: int
    is_late: bool
    late_by_minutes: int
    is_early_departure: bool
    early_departure_minutes: int
    status: str


# ─── Core calculations ─────────────────────────────────────────────────────────

def calc_lateness(
    punch_in: datetime,
    expected_start: time,
    grace_minutes: int,
    tz_name: str,
) -> LatenessResult:
    local = to_tz(punch_in, tz_name)
    expected = local.replace(
        hour=expected_start.hour, minute=expected_start.minute,
        second=0, microsecond=0,
    )
    raw_late = max(0, int((local - expected).total_seconds() / 60))
    net_late = max(0, raw_late - grace_minutes)
    return LatenessResult(net_late > 0, net_late)


def calc_early_departure(
    punch_out: datetime,
    expected_end: time,
    grace_minutes: int,
    tz_name: str,
) -> EarlyDepartureResult:
    local = to_tz(punch_out, tz_name)
    expected = local.replace(
        hour=expected_end.hour, minute=expected_end.minute,
        second=0, microsecond=0,
    )
    raw_early = max(0, int((expected - local).total_seconds() / 60))
    net_early = max(0, raw_early - grace_minutes)
    return EarlyDepartureResult(net_early > 0, net_early)


def calc_overtime(
    effective_minutes: int,
    standard_minutes: int,
    ot_enabled: bool,
    ot_qualifying_minutes: int,
    ot_daily_cap_minutes: int | None,
) -> OvertimeResult:
    """
    Determine overtime for a day.

    OT starts only after the employee has worked `ot_qualifying_minutes` beyond
    the standard working minutes (e.g. OT threshold = 30 means the employee
    must work at least 30 minutes extra before any OT is counted).
    """
    if not ot_enabled:
        return OvertimeResult(0, False)
    excess = effective_minutes - standard_minutes
    if excess < ot_qualifying_minutes:
        return OvertimeResult(0, False)
    ot = excess
    if ot_daily_cap_minutes is not None:
        ot = min(ot, ot_daily_cap_minutes)
    return OvertimeResult(ot, True)


def compute_standard_minutes(expected_start: time, expected_end: time, break_minutes: int) -> int:
    """Derive standard working minutes from policy start/end times."""
    start_dt = datetime.combine(date.today(), expected_start)
    end_dt = datetime.combine(date.today(), expected_end)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return max(0, int((end_dt - start_dt).total_seconds() / 60) - break_minutes)


def derive_attendance_status(
    punched_in: bool,
    effective_minutes: int,
    standard_minutes: int,
    half_day_threshold_pct: int,
    is_late: bool,
    is_early: bool,
) -> str:
    if not punched_in or effective_minutes == 0:
        return "ABSENT"
    threshold = (standard_minutes * half_day_threshold_pct) // 100
    if effective_minutes < threshold:
        return "HALF_DAY"
    if is_late:
        return "LATE"
    if is_early:
        return "EARLY_DEPARTURE"
    return "PRESENT"


def working_days_between(from_date: date, to_date: date, work_days: str) -> float:
    """
    Count working days between from_date and to_date inclusive.

    work_days: 7-char string "1111100" — index 0=Mon, 6=Sun, "1"=working day.
    Returns a float to support half-day counting at boundaries.
    """
    if len(work_days) != 7:
        work_days = "1111100"
    days = 0
    current = from_date
    while current <= to_date:
        if work_days[current.weekday()] == "1":
            days += 1
        current += timedelta(days=1)
    return float(days)


def compute_day(
    punch_in: datetime,
    punch_out: datetime,
    break_minutes: int,
    expected_start: time,
    expected_end: time,
    grace_late_minutes: int,
    grace_early_departure_minutes: int,
    half_day_threshold_pct: int,
    ot_enabled: bool,
    ot_qualifying_minutes: int,
    ot_daily_cap_minutes: int | None,
    tz_name: str,
    punch_rounding_minutes: int = 0,
    punch_rounding_direction: str = "NONE",
    break_auto_deduct: bool = False,
) -> DayComputeResult:
    """
    Full policy-driven computation for a single attendance day.

    Returns gross/effective/OT minutes + lateness + early departure + status.
    All values are derived from the policy — no hard-coded rules.
    """
    pi = apply_punch_rounding(punch_in, punch_rounding_minutes, punch_rounding_direction)
    po = apply_punch_rounding(punch_out, punch_rounding_minutes, punch_rounding_direction)

    gross = max(0, int((po - pi).total_seconds() / 60))
    break_deducted = break_minutes if break_auto_deduct else 0
    effective = max(0, gross - break_deducted)

    standard = compute_standard_minutes(expected_start, expected_end, break_minutes)

    late_res = calc_lateness(pi, expected_start, grace_late_minutes, tz_name)
    early_res = calc_early_departure(po, expected_end, grace_early_departure_minutes, tz_name)
    ot_res = calc_overtime(effective, standard, ot_enabled, ot_qualifying_minutes, ot_daily_cap_minutes)

    status = derive_attendance_status(
        punched_in=True,
        effective_minutes=effective,
        standard_minutes=standard,
        half_day_threshold_pct=half_day_threshold_pct,
        is_late=late_res.is_late,
        is_early=early_res.is_early,
    )

    return DayComputeResult(
        gross_minutes=gross,
        break_minutes=break_deducted,
        effective_minutes=effective,
        ot_minutes=ot_res.ot_minutes,
        is_late=late_res.is_late,
        late_by_minutes=late_res.late_by_minutes,
        is_early_departure=early_res.is_early,
        early_departure_minutes=early_res.early_by_minutes,
        status=status,
    )

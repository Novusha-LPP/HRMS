"""
Time module — Punch, AttendanceDay.

Punches are append-only. AttendanceDay is computed from punches and can
always be recomputed. Period close marks an attendance period as locked.
"""

import enum
from datetime import UTC, date, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class PunchType(enum.StrEnum):
    IN = "IN"
    OUT = "OUT"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"


class PunchSource(enum.StrEnum):
    WEB = "WEB"
    MOBILE = "MOBILE"
    DEVICE = "DEVICE"
    MANUAL = "MANUAL"  # HR correction
    INTEGRATION = "INTEGRATION"  # through a connected app's employee session (source_system)


class AttendanceStatus(enum.StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"
    LATE = "LATE"
    EARLY_DEPARTURE = "EARLY_DEPARTURE"
    ON_LEAVE = "ON_LEAVE"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"
    PENDING = "PENDING"  # punched in but not yet out
    MISSED_PUNCH = "MISSED_PUNCH"  # still checked in 24 hours later; needs a correction
    OFF_DAY_WORKED = "OFF_DAY_WORKED"  # worked on a weekly off or holiday


class OvertimeStatus(enum.StrEnum):
    NONE = "NONE"  # no OT computed for this day
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    # Extra time beyond the shift when no overtime policy is set: shown, never approved or paid.
    INFO = "INFO"


class ReviewFlag(enum.StrEnum):
    LEGACY_CONFLICT = "LEGACY_CONFLICT"  # HR must resolve the imported/native event sequence.
    # A break was started and never ended; it was counted only up to the policy break.
    BREAK_NOT_ENDED = "BREAK_NOT_ENDED"
    # Over LONG_DAY_MINUTES from first check-in to last check-out — usually a check-out the
    # next morning for a check-in that was never closed.
    LONG_DAY = "LONG_DAY"


LONG_DAY_MINUTES = 16 * 60


class Holiday(SQLModel, table=True):
    """
    A date marked as a holiday. legal_entity_id NULL means tenant-wide;
    set means specific to one company (different states/countries observe
    different holidays). Referenced by attendance-day status derivation
    (time/router.py) and by leave's working-day counting
    (core/datetime_utils.working_days_between).
    """

    __tablename__ = "holidays"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    holiday_date: date = Field()
    name: str = Field(max_length=200)
    legal_entity_id: UUID | None = Field(default=None)
    is_optional: bool = Field(default=False)
    calendar_id: UUID | None = Field(default=None)
    holiday_type: str | None = Field(default=None, max_length=50)
    # On the holiday list: a day off only for people whose calendar includes it. Otherwise a
    # holiday on no calendar is a day off for everyone (or its legal entity).
    is_library: bool = Field(default=False)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class HolidayCalendar(SQLModel, table=True):
    __tablename__ = "holiday_calendars"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=100)
    year: int
    recorded_at: datetime | None = Field(default=None)
    archived_at: datetime | None = Field(default=None)


class HolidayCalendarDay(SQLModel, table=True):
    """
    A holiday on a calendar. Holidays are one shared list per tenant, so a date that several
    calendars observe is one row; whether it is optional is per calendar.
    """

    __tablename__ = "holiday_calendar_days"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    calendar_id: UUID
    holiday_id: UUID
    is_optional: bool = Field(default=False)
    recorded_at: datetime | None = Field(default=None)


class HolidayCalendarAssignment(SQLModel, table=True):
    """
    Who follows a calendar: one employee, a department (with its sub-units), a legal entity, or
    — with no target set — the whole company. The most specific assignment wins; see the
    holiday_calendar_for() SQL function (migration 0047).
    """

    __tablename__ = "holiday_calendar_assignments"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID | None = Field(default=None, index=True)
    legal_entity_id: UUID | None = Field(default=None)
    org_unit_id: UUID | None = Field(default=None)
    calendar_id: UUID
    effective_from: date
    effective_to: date | None = None
    recorded_at: datetime | None = None
    archived_at: datetime | None = None


class Punch(SQLModel, table=True):
    """
    Raw punch event — immutable once created.
    HR corrections create a new punch with is_corrected=True and link to original.
    """

    __tablename__ = "punches"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    punch_type: str = Field(max_length=20)
    punched_at: datetime = Field()
    work_date: date | None = Field(default=None, index=True)
    source: str = Field(default=PunchSource.WEB, max_length=20)
    # The connected app's code when source is INTEGRATION (migration 0051).
    source_system: str | None = Field(default=None, max_length=40)
    # GPS
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    device_id: str | None = Field(default=None, max_length=100)
    # S3 key for selfie image
    selfie_key: str | None = Field(default=None, max_length=500)
    # Correction chain
    is_corrected: bool = Field(default=False)
    original_punch_id: UUID | None = Field(default=None)
    correction_reason: str | None = Field(default=None, max_length=255)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)


class AttendanceDay(SQLModel, table=True):
    """
    One row per employment per calendar day.
    Computed from punches + leave data; recomputable.
    """

    __tablename__ = "attendance_days"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    work_date: date = Field(index=True)
    first_punch_in: datetime | None = Field(default=None)
    last_punch_out: datetime | None = Field(default=None)
    # Minutes
    gross_minutes: int = Field(default=0)
    break_minutes: int = Field(default=0)
    effective_minutes: int = Field(default=0)
    late_by_minutes: int = Field(default=0)
    early_departure_minutes: int = Field(default=0)
    status: str = Field(default=AttendanceStatus.PENDING, max_length=20)
    # Overtime — computed by the same policy-driven engine as everything else
    # above (see core/datetime_utils.compute_day), but requires a human
    # review before it counts as approved. Recomputing (a later correction)
    # resets status back to PENDING/NONE — see _apply_ot in time/router.py
    # and corrections/router.py, the two places that write these fields.
    ot_minutes: int = Field(default=0)
    ot_status: str = Field(default=OvertimeStatus.NONE, max_length=20)
    ot_reviewed_by: UUID | None = Field(default=None)
    ot_reviewed_at: datetime | None = Field(default=None)
    ot_review_notes: str | None = Field(default=None, max_length=500)
    # Comp-off days this day earned (work on an off day under a COMP_OFF policy) — credited to
    # the comp-off leave balance; see leave/comp_off.py.
    comp_off_days: float = Field(default=0)
    # Why HR should look at the day, comma-separated ReviewFlag values (None = nothing to
    # check). Overtime and comp-off wait until someone in HR marks it reviewed.
    review_flags: str | None = Field(default=None, max_length=60)
    reviewed_by: UUID | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)
    is_locked: bool = Field(default=False)  # locked by period close
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)


def apply_overtime(ad: AttendanceDay, ot_minutes: int, payable: bool = True) -> None:
    """
    Write freshly-computed OT onto an AttendanceDay. Shared by time/router.py
    (punch-out) and corrections/router.py (post-approval recompute) — both
    call core.datetime_utils.compute_day() and need identical review-reset
    behavior: an unchanged minute count leaves an existing review alone, but
    a correction that changes the number invalidates any prior approval
    rather than leaving a stale APPROVED status on top of different minutes.

    With `payable=False` (no overtime policy) the minutes are recorded as INFO: visible only,
    never pending approval and never passed to payroll.
    """
    target = OvertimeStatus.PENDING if payable else OvertimeStatus.INFO
    unchanged_kind = (ad.ot_status == OvertimeStatus.INFO) == (not payable)
    if ad.ot_minutes == ot_minutes and ad.ot_status != OvertimeStatus.NONE and unchanged_kind:
        return
    ad.ot_minutes = ot_minutes
    ad.ot_status = target if ot_minutes > 0 else OvertimeStatus.NONE
    ad.ot_reviewed_by = None
    ad.ot_reviewed_at = None
    ad.ot_review_notes = None

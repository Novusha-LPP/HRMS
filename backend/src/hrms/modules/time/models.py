"""
Time module — Punch, AttendanceDay.

Punches are append-only. AttendanceDay is computed from punches and can
always be recomputed. Period close marks an attendance period as locked.
"""

import enum
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class PunchType(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"


class PunchSource(str, enum.Enum):
    WEB = "WEB"
    MOBILE = "MOBILE"
    DEVICE = "DEVICE"
    MANUAL = "MANUAL"  # HR correction


class AttendanceStatus(str, enum.Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"
    LATE = "LATE"
    EARLY_DEPARTURE = "EARLY_DEPARTURE"
    ON_LEAVE = "ON_LEAVE"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"
    PENDING = "PENDING"  # punched in but not yet out


class OvertimeStatus(str, enum.Enum):
    NONE = "NONE"  # no OT computed for this day
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


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
    legal_entity_id: Optional[UUID] = Field(default=None)
    is_optional: bool = Field(default=False)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


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
    source: str = Field(default=PunchSource.WEB, max_length=20)
    # GPS
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)
    device_id: Optional[str] = Field(default=None, max_length=100)
    # S3 key for selfie image
    selfie_key: Optional[str] = Field(default=None, max_length=500)
    # Correction chain
    is_corrected: bool = Field(default=False)
    original_punch_id: Optional[UUID] = Field(default=None)
    correction_reason: Optional[str] = Field(default=None, max_length=255)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)


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
    first_punch_in: Optional[datetime] = Field(default=None)
    last_punch_out: Optional[datetime] = Field(default=None)
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
    ot_reviewed_by: Optional[UUID] = Field(default=None)
    ot_reviewed_at: Optional[datetime] = Field(default=None)
    ot_review_notes: Optional[str] = Field(default=None, max_length=500)
    is_locked: bool = Field(default=False)  # locked by period close
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)


def apply_overtime(ad: AttendanceDay, ot_minutes: int) -> None:
    """
    Write freshly-computed OT onto an AttendanceDay. Shared by time/router.py
    (punch-out) and corrections/router.py (post-approval recompute) — both
    call core.datetime_utils.compute_day() and need identical review-reset
    behavior: an unchanged minute count leaves an existing review alone, but
    a correction that changes the number invalidates any prior approval
    rather than leaving a stale APPROVED status on top of different minutes.
    """
    if ad.ot_minutes == ot_minutes and ad.ot_status != OvertimeStatus.NONE:
        return
    ad.ot_minutes = ot_minutes
    ad.ot_status = OvertimeStatus.PENDING if ot_minutes > 0 else OvertimeStatus.NONE
    ad.ot_reviewed_by = None
    ad.ot_reviewed_at = None
    ad.ot_review_notes = None

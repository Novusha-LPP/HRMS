"""
Time module — Shift, Punch, AttendanceDay.

Punches are append-only. AttendanceDay is computed from punches and can
always be recomputed. Period close marks an attendance period as locked.
"""

import enum
from datetime import date, datetime, time, timezone
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


class Shift(SQLModel, table=True):
    __tablename__ = "shifts"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=100)
    start_time: time = Field()
    end_time: time = Field()
    break_minutes: int = Field(default=30)
    # Bitmask: Mon=1, Tue=2, Wed=4, Thu=8, Fri=16, Sat=32, Sun=64
    work_days: int = Field(default=31)  # Mon-Fri
    grace_late_minutes: int = Field(default=10)
    grace_early_departure_minutes: int = Field(default=10)
    is_default: bool = Field(default=False)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)


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
    Computed from punches + shift + leave data; recomputable.
    """
    __tablename__ = "attendance_days"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    work_date: date = Field(index=True)
    shift_id: Optional[UUID] = Field(default=None)
    first_punch_in: Optional[datetime] = Field(default=None)
    last_punch_out: Optional[datetime] = Field(default=None)
    # Minutes
    gross_minutes: int = Field(default=0)
    break_minutes: int = Field(default=0)
    effective_minutes: int = Field(default=0)
    late_by_minutes: int = Field(default=0)
    early_departure_minutes: int = Field(default=0)
    status: str = Field(default=AttendanceStatus.PENDING, max_length=20)
    is_locked: bool = Field(default=False)  # locked by period close
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)

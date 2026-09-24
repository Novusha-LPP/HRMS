from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from hrms.modules.time.models import AttendanceStatus, PunchSource, PunchType


class PunchCreate(BaseModel):
    punch_type: PunchType
    punched_at: Optional[datetime] = None  # defaults to now() server-side
    source: PunchSource = PunchSource.WEB
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    device_id: Optional[str] = None


class PunchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    employment_id: str
    punch_type: PunchType
    punched_at: datetime
    source: PunchSource
    latitude: Optional[float]
    longitude: Optional[float]
    is_corrected: bool


class TodayStatusResponse(BaseModel):
    """What the employee sees when they open the punch clock."""
    employment_id: str
    work_date: date
    is_punched_in: bool
    first_punch_in: Optional[datetime]
    last_punch_out: Optional[datetime]
    effective_minutes: int
    status: AttendanceStatus
    # All punches today, for the timeline
    punches: list[PunchResponse]


class AttendanceDayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    employment_id: str
    work_date: date
    first_punch_in: Optional[datetime]
    last_punch_out: Optional[datetime]
    effective_minutes: int
    late_by_minutes: int
    early_departure_minutes: int
    status: AttendanceStatus
    is_locked: bool


class ShiftCreate(BaseModel):
    name: str
    start_time: str  # "09:00"
    end_time: str    # "18:00"
    break_minutes: int = 30
    work_days: int = 31
    grace_late_minutes: int = 10
    grace_early_departure_minutes: int = 10
    is_default: bool = False


class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    start_time: str
    end_time: str
    break_minutes: int
    work_days: int
    is_default: bool
    status: str

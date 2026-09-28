from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hrms.modules.time.models import AttendanceStatus, OvertimeStatus, PunchSource, PunchType


class PunchCreate(BaseModel):
    punch_type: PunchType
    punched_at: datetime | None = None  # defaults to now() server-side
    source: PunchSource = PunchSource.WEB
    latitude: float | None = None
    longitude: float | None = None
    device_id: str | None = None


class PunchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    employment_id: str
    punch_type: PunchType
    punched_at: datetime
    source: PunchSource
    latitude: float | None
    longitude: float | None
    is_corrected: bool


class TodayStatusResponse(BaseModel):
    """What the employee sees when they open the punch clock."""

    employment_id: str
    work_date: date
    is_punched_in: bool
    first_punch_in: datetime | None
    last_punch_out: datetime | None
    effective_minutes: int
    status: AttendanceStatus
    # All punches today, for the timeline
    punches: list[PunchResponse]


class AttendanceDayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    employment_id: str
    work_date: date
    first_punch_in: datetime | None
    last_punch_out: datetime | None
    effective_minutes: int
    late_by_minutes: int
    early_departure_minutes: int
    status: AttendanceStatus
    is_locked: bool
    ot_minutes: int = 0
    ot_status: OvertimeStatus = OvertimeStatus.NONE
    ot_reviewed_by: str | None = None
    ot_reviewed_at: datetime | None = None
    ot_review_notes: str | None = None


class OvertimeReviewRequest(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    notes: str | None = Field(default=None, max_length=500)


class PendingOvertimeItem(BaseModel):
    attendance_day_id: str
    employment_id: str
    employee_number: str
    name: str
    department: str | None = None
    work_date: date
    effective_minutes: int
    ot_minutes: int
    ot_status: OvertimeStatus


class HolidayCreate(BaseModel):
    holiday_date: date
    name: str = Field(max_length=200)
    legal_entity_id: str | None = Field(default=None, description="Omit for a tenant-wide holiday")
    is_optional: bool = False


class HolidayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    holiday_date: date
    name: str
    legal_entity_id: str | None
    is_optional: bool


class DailyEmployeeRecord(BaseModel):
    employment_id: str
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


class DailyMetrics(BaseModel):
    total_headcount: int = 0
    present_count: int = 0
    on_time_count: int = 0
    late_count: int = 0
    absent_count: int = 0
    on_leave_count: int = 0
    half_day_count: int = 0
    presence_rate: float = 0.0
    average_work_minutes: int = 0
    total_overtime_minutes: int = 0


class DepartmentAttendanceStat(BaseModel):
    department: str
    total: int
    present: int
    late: int
    absent: int
    on_leave: int
    presence_rate: float


class HourlyArrivalStat(BaseModel):
    hour: str
    count: int


class DailyAnalysisResponse(BaseModel):
    work_date: date
    metrics: DailyMetrics
    department_stats: list[DepartmentAttendanceStat]
    hourly_arrivals: list[HourlyArrivalStat]
    employees: list[DailyEmployeeRecord]

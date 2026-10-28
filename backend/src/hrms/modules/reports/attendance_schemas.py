"""Read-only monthly attendance report contract."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class AttendanceSummaryMetrics(BaseModel):
    total_working_days: float = 0
    present_days: float = 0
    absent_days: float = 0
    half_day_pl: int = 0
    full_day_pl: int = 0
    total_pl_taken: float = 0
    lwp_taken: float = 0
    other_leave_days: float = 0
    week_off_days: int = 0
    holiday_days: int = 0
    opening_balance: float | None = None
    pl_taken: float | None = None
    available_balance: float | None = None
    total_work_minutes: int = 0
    worked_days: int = 0
    average_hours_per_day: float | None = None
    late_days: int = 0
    early_departure_days: int = 0
    # Working days of people whose attendance is marked (time/marking.py) that nobody marked.
    not_marked_days: int = 0


class AttendanceSummaryDay(BaseModel):
    work_date: date
    day_name: str
    shift_start: str
    shift_end: str
    timezone: str
    status: str
    display_status: str | None = None
    shift_name: str | None = None
    is_off_day: bool = False
    first_punch_in: datetime | None = None
    last_punch_out: datetime | None = None
    effective_minutes: int = 0
    late_by_minutes: int = 0
    early_departure_minutes: int = 0
    leave_type: str | None = None
    paid_leave_days: float = 0
    lwp_days: float = 0
    other_leave_days: float = 0
    half_day_pl: int = 0
    full_day_pl: int = 0
    is_working_day: bool
    holiday_name: str | None = None
    department_id: str | None = None
    department: str | None = None


class AttendanceSummaryEmployee(AttendanceSummaryMetrics):
    employment_id: str
    employee_number: str
    name: str
    legal_entity_id: str
    company: str
    department_id: str | None = None
    department: str | None = None
    days: list[AttendanceSummaryDay] = Field(default_factory=list)


class AttendanceSummaryCompany(AttendanceSummaryMetrics):
    legal_entity_id: str
    company: str
    employee_count: int


class AttendanceSummaryTotals(AttendanceSummaryMetrics):
    employee_count: int = 0


class AttendanceSummaryReport(BaseModel):
    from_date: date
    to_date: date
    generated_at: datetime
    employees: list[AttendanceSummaryEmployee]
    companies: list[AttendanceSummaryCompany]
    totals: AttendanceSummaryTotals
    notes: list[str]

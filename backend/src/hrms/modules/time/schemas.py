from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hrms.modules.time.models import AttendanceStatus, OvertimeStatus, PunchSource, PunchType


class PunchCreate(BaseModel):
    punch_type: PunchType
    punched_at: datetime | None = None  # defaults to now() server-side
    source: PunchSource = PunchSource.WEB
    latitude: float | None = None
    longitude: float | None = None
    device_id: str | None = None
    # Checking out after more than 16 hours (usually the morning after a forgotten check-out)
    # is refused with code LONG_DAY_CONFIRM until the employee confirms it.
    confirm_long_day: bool = False


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
    comp_off_days: float = 0
    # Why HR should check the day (BREAK_NOT_ENDED, LONG_DAY); overtime and comp-off wait for it.
    review_flags: list[str] = []
    needs_review: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


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
    calendar_id: str | None = None
    calendar_name: str | None = None
    holiday_type: str | None = None


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
    comp_off_days: float = 0
    review_flags: list[str] = []
    needs_review: bool = False
    attendance_day_id: str | None = None
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
    snapshot_id: UUID | None = None
    generated_at: datetime | None = None
    total_filtered: int = 0
    work_date: date
    metrics: DailyMetrics
    department_stats: list[DepartmentAttendanceStat]
    hourly_arrivals: list[HourlyArrivalStat]
    employees: list[DailyEmployeeRecord]


# ─── Attendance register (one employee, day by day) ──────────────────────────


class RegisterEmployee(BaseModel):
    employment_id: str
    employee_number: str
    name: str
    legal_entity_id: str
    company: str
    department_id: str | None = None
    department: str | None = None


class RegisterCompany(BaseModel):
    id: str
    name: str


class RegisterDepartment(BaseModel):
    id: str
    name: str
    legal_entity_id: str


class RegisterFilters(BaseModel):
    companies: list[RegisterCompany]
    departments: list[RegisterDepartment]


class RegisterPunch(BaseModel):
    id: str
    punch_type: str
    punched_at: datetime
    source: str
    is_corrected: bool
    correction_reason: str | None = None


class RegisterDay(BaseModel):
    work_date: date
    # Stored status when the day has punches; otherwise ON_LEAVE, HOLIDAY, WEEKEND, UPCOMING or
    # ABSENT, worked out the same way as Daily Analysis.
    status: str
    is_off_day: bool = False
    holiday_name: str | None = None
    leave_type: str | None = None
    attendance_day_id: str | None = None
    first_punch_in: datetime | None = None
    last_punch_out: datetime | None = None
    effective_minutes: int = 0
    gross_minutes: int = 0
    break_minutes: int = 0
    late_by_minutes: int = 0
    early_departure_minutes: int = 0
    ot_minutes: int = 0
    ot_status: OvertimeStatus = OvertimeStatus.NONE
    comp_off_days: float = 0
    review_flags: list[str] = []
    needs_review: bool = False
    is_locked: bool = False
    shift_start: str
    shift_end: str
    timezone: str
    # The policy figures behind the status, so an editor can preview the result of a change.
    policy_break_minutes: int = 0
    grace_late_minutes: int = 0
    grace_early_minutes: int = 0
    standard_minutes: int = 0
    half_day_minutes: int = 0
    punches: list[RegisterPunch] = []


class RegisterResponse(BaseModel):
    employment_id: str
    employee_number: str
    name: str
    department: str | None = None
    designation: str | None = None
    from_date: date
    to_date: date
    days: list[RegisterDay]


class DayPunch(BaseModel):
    punch_type: Literal["IN", "OUT", "BREAK_START", "BREAK_END"]
    punched_at: datetime

    @field_validator("punched_at")
    @classmethod
    def _must_be_an_instant(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("must include a timezone offset, e.g. 2026-09-27T09:00:00+05:30")
        return v


class DayPunchesUpdate(BaseModel):
    """The day's complete punch list as it should be — an empty list marks the day absent."""

    punches: list[DayPunch] = Field(default_factory=list, max_length=40)
    reason: str = Field(min_length=3, max_length=255)


# ─── Holiday calendars ────────────────────────────────────────────────────────

CalendarTarget = Literal["COMPANY", "LEGAL_ENTITY", "DEPARTMENT", "EMPLOYEE"]


class CalendarDayOut(BaseModel):
    id: str
    holiday_id: str
    holiday_date: date
    name: str
    holiday_type: str | None = None
    is_optional: bool = False
    # Other calendars that observe the same holiday (it is one shared row).
    shared_with: list[str] = []


class CalendarAssignmentOut(BaseModel):
    id: str
    target: CalendarTarget
    target_id: str | None = None
    target_name: str
    target_detail: str | None = None
    effective_from: date
    effective_to: date | None = None


class HolidayCalendarOut(BaseModel):
    id: str
    name: str
    year: int
    days: list[CalendarDayOut]
    assignments: list[CalendarAssignmentOut]
    # Active employees who follow this calendar today.
    people: int = 0


class HolidayCalendarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=2000, le=2100)
    holiday_ids: list[str] = Field(default_factory=list, description="Holidays from the list")
    copy_from: str | None = Field(default=None, description="Copy the days of this calendar")
    assign_company: bool = Field(default=False, description="Make it the company-wide calendar")


class HolidayCalendarUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CalendarDayCreate(BaseModel):
    """An existing holiday (holiday_id), or a date and name — reused if that date already exists."""

    holiday_id: str | None = None
    holiday_date: date | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_optional: bool = False

    @model_validator(mode="after")
    def _one_way(self):
        if not self.holiday_id and not (self.holiday_date and self.name and self.name.strip()):
            raise ValueError("Choose a holiday, or give its date and name")
        return self


class CalendarDayUpdate(BaseModel):
    is_optional: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)


class CalendarAssignmentCreate(BaseModel):
    target: CalendarTarget
    target_id: str | None = None
    effective_from: date | None = Field(
        default=None, description="Defaults to 1 January of the calendar's year"
    )
    effective_to: date | None = None
    replace: bool = Field(
        default=False, description="End whatever calendar this target follows now"
    )

    @model_validator(mode="after")
    def _target(self):
        if (self.target == "COMPANY") != (self.target_id is None):
            raise ValueError(
                "Give target_id for an entity, department or employee, never for COMPANY"
            )
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValueError("The end date must not precede the start")
        return self


class CalendarCoverage(BaseModel):
    calendar_id: str | None
    name: str
    people: int


class LibraryCalendarRef(BaseModel):
    id: str
    name: str
    is_optional: bool = False


class LibraryHoliday(BaseModel):
    """A holiday on the year's holiday list, and the calendars that include it."""

    id: str
    holiday_date: date
    name: str
    holiday_type: str | None = None
    calendars: list[LibraryCalendarRef] = []


class LibraryHolidayCreate(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=200)


class LibraryHolidayUpdate(BaseModel):
    holiday_date: date | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)


class CalendarDayChoice(BaseModel):
    holiday_id: str
    is_optional: bool = False


class CalendarDaysSet(BaseModel):
    """The calendar's complete selection from the holiday list."""

    holidays: list[CalendarDayChoice] = Field(default_factory=list, max_length=200)


# ─── Marked attendance (time/marking.py) ─────────────────────────────────────


class MarkInfo(BaseModel):
    status: str | None  # PRESENT / ABSENT, or None when the mark was cleared
    punch_in: datetime | None = None
    punch_out: datetime | None = None
    remark: str | None
    marked_by: str | None
    marked_at: datetime
    source: str


class MarkingRow(BaseModel):
    employment_id: str
    employee_number: str | None
    name: str
    company: str
    department: str | None
    group_id: str
    group_name: str
    # What the caller may do with this person's day: MARK or VIEW.
    access: Literal["VIEW", "MARK"]
    # PRESENT / ABSENT (marked), NOT_MARKED, ON_LEAVE, HOLIDAY, WEEKEND, UPCOMING,
    # OFF_DAY_WORKED (marked present on a day off), or a punched day's own status.
    status: str
    is_off_day: bool
    holiday_name: str | None = None
    leave_type: str | None = None
    # The person's own punches (a day with them is computed from them and can't be marked).
    has_punches: bool = False
    # Times a marker entered: the day's hours, lateness and overtime come from them.
    punch_in: datetime | None = None
    punch_out: datetime | None = None
    worked_minutes: int = 0
    late_by_minutes: int = 0
    # The person's policy clock: times are entered and shown on it.
    timezone: str = "Asia/Kolkata"
    is_locked: bool = False
    can_mark: bool
    blocked_reason: str | None = None
    mark: MarkInfo | None = None


class MarkingResponse(BaseModel):
    work_date: date
    rows: list[MarkingRow]
    counts: dict[str, int]


class MarkEntry(BaseModel):
    employment_id: str
    # None clears the mark: the day goes back to "Not marked".
    status: Literal["PRESENT", "ABSENT"] | None
    # Optional times on the person's own clock (policy timezone), "HH:MM". With times the day
    # counts like punches (hours, late, half day, overtime). An out time not after the in time
    # is the next morning (night shift). Times need status PRESENT.
    punch_in: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    punch_out: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    remark: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def times_go_with_present(self):
        if self.punch_out and not self.punch_in:
            raise ValueError("An out time needs an in time")
        if self.punch_in and self.status != "PRESENT":
            raise ValueError("Times can only be given with status PRESENT")
        if self.punch_out and self.punch_out == self.punch_in:
            raise ValueError("The out time can't be the same as the in time")
        return self


class MarkingUpdate(BaseModel):
    marks: list[MarkEntry] = Field(min_length=1, max_length=500)
    # Used for every row that has no remark of its own.
    remark: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def one_row_per_person(self):
        ids = [m.employment_id for m in self.marks]
        if len(ids) != len(set(ids)):
            raise ValueError("Each employee can appear only once")
        return self


class MarkingResult(BaseModel):
    work_date: date
    changed: int
    unchanged: int
    rows: list[MarkingRow]


class MarkingLeaveType(BaseModel):
    id: str
    name: str
    code: str
    is_paid: bool


class MarkingLeaveRequest(BaseModel):
    employment_id: str
    leave_type_id: str
    from_date: date
    to_date: date
    half_day_option: Literal["NONE", "FIRST_HALF", "SECOND_HALF"] = "NONE"
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.to_date < self.from_date:
            raise ValueError("to_date must not precede from_date")
        if (self.to_date - self.from_date).days > 92:
            raise ValueError("Record at most 93 days of leave at a time")
        if self.half_day_option != "NONE" and self.to_date != self.from_date:
            raise ValueError("Half-day leave must cover exactly one date")
        return self


class AttendanceGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Only people of this company can join, if set.
    legal_entity_id: str | None = None


class AttendanceGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    legal_entity_id: str | None = None


class AttendanceGroupResponse(BaseModel):
    id: str
    name: str
    description: str | None
    legal_entity_id: str | None
    company: str | None
    member_count: int
    # What the caller may do: MARK (also everything HR managing groups can), VIEW.
    my_access: Literal["VIEW", "MARK"]
    can_manage: bool


class GroupMember(BaseModel):
    employment_id: str
    employee_number: str | None
    name: str
    company: str
    department: str | None
    effective_from: date


class GroupMembersAdd(BaseModel):
    employment_ids: list[str] = Field(min_length=1, max_length=500)
    effective_from: date


class GroupAccessGrant(BaseModel):
    access_level: Literal["VIEW", "MARK"]


class GroupAccessEntry(BaseModel):
    user_account_id: str
    name: str
    email: str | None
    access_level: Literal["VIEW", "MARK"]

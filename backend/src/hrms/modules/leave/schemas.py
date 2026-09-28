from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LeaveTypeCreate(BaseModel):
    name: str = Field(max_length=100)
    code: str = Field(max_length=10)
    days_per_year: float = Field(ge=0)
    carry_forward: bool = False
    max_carry_forward_days: float | None = Field(default=None, ge=0)
    requires_approval: bool = True
    approval_levels: int = Field(default=1, ge=1, le=3)
    cancel_requires_approval: bool = False
    cancel_approval_levels: int = Field(default=1, ge=1, le=3)
    min_days_per_application: float = 0.5
    max_days_per_application: float | None = Field(default=None, ge=0)
    advance_notice_days: int = 0
    requires_document: bool = False
    is_paid: bool = True
    color: str = "#3B82F6"
    is_comp_off: bool = False
    encashable: bool = False
    accrual_enabled: bool = False


class LeaveTypeUpdate(BaseModel):
    name: str | None = None
    days_per_year: float | None = Field(default=None, ge=0)
    carry_forward: bool | None = None
    max_carry_forward_days: float | None = Field(default=None, ge=0)
    requires_approval: bool | None = None
    approval_levels: int | None = Field(default=None, ge=1, le=3)
    cancel_requires_approval: bool | None = None
    cancel_approval_levels: int | None = Field(default=None, ge=1, le=3)
    min_days_per_application: float | None = Field(default=None, ge=0)
    max_days_per_application: float | None = Field(default=None, ge=0)
    advance_notice_days: int | None = Field(default=None, ge=0)
    requires_document: bool | None = None
    is_paid: bool | None = None
    is_active: bool | None = None
    color: str | None = None
    is_comp_off: bool | None = None
    encashable: bool | None = None
    accrual_enabled: bool | None = None


class LeaveTypeResponse(LeaveTypeCreate):
    id: str
    is_active: bool


class LeaveBalanceResponse(BaseModel):
    id: str
    employment_id: str
    leave_type_id: str
    leave_type_name: str
    leave_type_code: str
    year: int
    allocated_days: float
    carry_forward_days: float
    used_days: float
    pending_days: float
    available_days: float
    color: str


class LeaveApplyRequest(BaseModel):
    leave_type_id: str
    from_date: date
    to_date: date
    half_day_option: Literal["NONE", "FIRST_HALF", "SECOND_HALF"] = "NONE"
    document_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.to_date < self.from_date:
            raise ValueError("to_date must not precede from_date")
        if (self.to_date - self.from_date).days > 366:
            raise ValueError("Apply for at most 367 calendar days at a time")
        if self.half_day_option != "NONE" and self.to_date != self.from_date:
            raise ValueError("Half-day leave must cover exactly one date")
        return self


class LeaveCancelRequest(BaseModel):
    cancel_reason: str | None = None


class LeaveApprovalActionRequest(BaseModel):
    action: str  # APPROVE or REJECT
    comments: str | None = None


class LeaveApprovalActionResponse(BaseModel):
    id: str
    application_id: str
    action_type: str
    level: int
    approver_employment_id: str | None
    comments: str | None
    actioned_at: datetime


class CompOffGrantRequest(BaseModel):
    employment_id: str = Field(
        description="Employee being credited — an HR/admin action, not self-service"
    )
    work_date: date
    days_granted: float = Field(default=1.0, gt=0)
    notes: str | None = None


class CompOffGrantResponse(BaseModel):
    id: str
    employment_id: str
    work_date: date
    days_granted: float
    notes: str | None
    granted_by: str | None
    recorded_at: datetime


class LeaveEncashmentRequest(BaseModel):
    employment_id: str = Field(
        description="Employee being paid out — an HR/admin action, not self-service"
    )
    leave_type_id: str
    days: float = Field(gt=0)
    effective_date: date | None = None
    notes: str | None = None


class LeaveEncashmentResponse(BaseModel):
    id: str
    employment_id: str
    leave_type_id: str
    leave_type_name: str
    days: float
    effective_date: date
    notes: str | None
    processed_by: str | None
    recorded_at: datetime


class AccrualRunResponse(BaseModel):
    period: str
    balances_credited: int
    days_credited_total: float


class LeaveApplicationResponse(BaseModel):
    id: str
    employment_id: str
    leave_type_id: str
    leave_type_name: str
    leave_type_code: str
    leave_type_color: str
    from_date: date
    to_date: date
    days_requested: float
    half_day_option: str
    reason: str | None
    status: str
    current_level: int
    total_levels: int
    applied_at: datetime | None
    cancel_reason: str | None
    cancel_requested_at: datetime | None
    approval_history: list[LeaveApprovalActionResponse] = []

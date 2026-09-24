from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class LeaveTypeCreate(BaseModel):
    name: str = Field(max_length=100)
    code: str = Field(max_length=10)
    days_per_year: float = Field(ge=0)
    carry_forward: bool = False
    max_carry_forward_days: Optional[float] = None
    requires_approval: bool = True
    approval_levels: int = Field(default=1, ge=1, le=3)
    cancel_requires_approval: bool = False
    cancel_approval_levels: int = Field(default=1, ge=1, le=3)
    min_days_per_application: float = 0.5
    max_days_per_application: Optional[float] = None
    advance_notice_days: int = 0
    requires_document: bool = False
    is_paid: bool = True
    color: str = "#3B82F6"


class LeaveTypeUpdate(BaseModel):
    name: Optional[str] = None
    days_per_year: Optional[float] = None
    carry_forward: Optional[bool] = None
    max_carry_forward_days: Optional[float] = None
    requires_approval: Optional[bool] = None
    approval_levels: Optional[int] = None
    cancel_requires_approval: Optional[bool] = None
    cancel_approval_levels: Optional[int] = None
    min_days_per_application: Optional[float] = None
    max_days_per_application: Optional[float] = None
    advance_notice_days: Optional[int] = None
    requires_document: Optional[bool] = None
    is_paid: Optional[bool] = None
    is_active: Optional[bool] = None
    color: Optional[str] = None


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
    half_day_option: str = "NONE"
    reason: Optional[str] = None


class LeaveCancelRequest(BaseModel):
    cancel_reason: Optional[str] = None


class LeaveApprovalActionRequest(BaseModel):
    action: str  # APPROVE or REJECT
    comments: Optional[str] = None


class LeaveApprovalActionResponse(BaseModel):
    id: str
    application_id: str
    action_type: str
    level: int
    approver_employment_id: Optional[str]
    comments: Optional[str]
    actioned_at: datetime


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
    reason: Optional[str]
    status: str
    current_level: int
    total_levels: int
    applied_at: Optional[datetime]
    cancel_reason: Optional[str]
    cancel_requested_at: Optional[datetime]
    approval_history: list[LeaveApprovalActionResponse] = []

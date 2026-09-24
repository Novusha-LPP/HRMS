from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class LeaveApplicationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_L1 = "PENDING_L1"
    PENDING_L2 = "PENDING_L2"
    PENDING_L3 = "PENDING_L3"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CANCEL_PENDING_L1 = "CANCEL_PENDING_L1"
    CANCEL_PENDING_L2 = "CANCEL_PENDING_L2"
    CANCEL_PENDING_L3 = "CANCEL_PENDING_L3"
    CANCEL_REJECTED = "CANCEL_REJECTED"


class LeaveApprovalActionType(str, enum.Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CANCEL_APPROVE = "CANCEL_APPROVE"
    CANCEL_REJECT = "CANCEL_REJECT"


class LeaveType(SQLModel, table=True):
    __tablename__ = "leave_types"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    name: str = Field(max_length=100)
    code: str = Field(max_length=10)
    days_per_year: float = Field(ge=0)
    carry_forward: bool = Field(default=False)
    max_carry_forward_days: Optional[float] = Field(default=None)
    requires_approval: bool = Field(default=True)
    approval_levels: int = Field(default=1, ge=1, le=3)
    cancel_requires_approval: bool = Field(default=False)
    cancel_approval_levels: int = Field(default=1, ge=1, le=3)
    min_days_per_application: float = Field(default=0.5, ge=0)
    max_days_per_application: Optional[float] = Field(default=None)
    advance_notice_days: int = Field(default=0, ge=0)
    requires_document: bool = Field(default=False)
    is_paid: bool = Field(default=True)
    is_active: bool = Field(default=True)
    color: str = Field(default="#3B82F6", max_length=20)


class LeaveBalance(SQLModel, table=True):
    __tablename__ = "leave_balances"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    employment_id: UUID = Field(index=True)
    leave_type_id: UUID = Field(index=True)
    year: int
    allocated_days: float = Field(default=0.0, ge=0)
    carry_forward_days: float = Field(default=0.0, ge=0)
    used_days: float = Field(default=0.0, ge=0)
    pending_days: float = Field(default=0.0, ge=0)


class LeaveApplication(SQLModel, table=True):
    __tablename__ = "leave_applications"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    employment_id: UUID = Field(index=True)
    leave_type_id: UUID
    from_date: date
    to_date: date
    days_requested: float
    half_day_option: str = Field(default="NONE", max_length=15)
    reason: Optional[str] = Field(default=None, max_length=1000)
    status: str = Field(default=LeaveApplicationStatus.DRAFT, max_length=25)
    current_level: int = Field(default=0)
    total_levels: int = Field(default=1)
    applied_at: Optional[datetime] = Field(default=None)
    cancel_reason: Optional[str] = Field(default=None, max_length=1000)
    cancel_requested_at: Optional[datetime] = Field(default=None)


class LeaveApprovalAction(SQLModel, table=True):
    __tablename__ = "leave_approval_actions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    application_id: UUID = Field(index=True)
    action_type: str = Field(max_length=20)
    level: int
    approver_employment_id: Optional[UUID] = Field(default=None)
    comments: Optional[str] = Field(default=None, max_length=1000)
    actioned_at: datetime

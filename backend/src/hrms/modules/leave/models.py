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
    # Marks the type comp-off grants land in (POST /v1/leave/comp-off) —
    # at most one such type per tenant is meaningful; the endpoint picks
    # whichever is marked, auto-creating one on first use if none exists.
    is_comp_off: bool = Field(default=False)
    # Unused balance in this type can be converted to a payout record via
    # POST /v1/leave/encashment. Off by default — most leave types (e.g.
    # sick leave) shouldn't be cashed out, only ones HR explicitly flags.
    encashable: bool = Field(default=False)
    # Whether POST /v1/leave/accrual/run credits this type monthly
    # (days_per_year / 12) instead of it only ever being set once via
    # POST /v1/leave/balances/init.
    accrual_enabled: bool = Field(default=False)


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
    # "YYYY-MM" of the last period this balance received its automatic
    # monthly accrual credit — see POST /v1/leave/accrual/run. Prevents
    # double-crediting if the same month is ever run twice.
    last_accrued_period: Optional[str] = Field(default=None, max_length=7)


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


class CompOffGrant(SQLModel, table=True):
    """
    One row per (employment, work_date) an employee was credited comp-off
    for working a holiday/weekend — the unique index on that pair is the
    idempotency guard against granting the same day twice.
    """
    __tablename__ = "comp_off_grants"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    work_date: date = Field()
    days_granted: float = Field()
    notes: Optional[str] = Field(default=None, max_length=500)
    granted_by: Optional[UUID] = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now())


class LeaveEncashment(SQLModel, table=True):
    """
    A record that N days of a leave type's balance were converted to a
    payout. This system has no payroll module (see gap analysis) — an
    encashment here reduces the balance and stands as the record for
    payroll to pick up externally; it does not itself move any money.
    """
    __tablename__ = "leave_encashments"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    leave_type_id: UUID = Field()
    days: float = Field()
    effective_date: date = Field()
    notes: Optional[str] = Field(default=None, max_length=500)
    processed_by: Optional[UUID] = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now())


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

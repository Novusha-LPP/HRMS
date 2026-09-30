from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class LeaveApplicationStatus(enum.StrEnum):
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


class LeaveApprovalActionType(enum.StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CANCEL_APPROVE = "CANCEL_APPROVE"
    CANCEL_REJECT = "CANCEL_REJECT"


class LeaveType(SQLModel, table=True):
    __tablename__ = "leave_types"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    name: str = Field(max_length=100)
    code: str = Field(max_length=10)
    days_per_year: float = Field(ge=0)
    carry_forward: bool = Field(default=False)
    max_carry_forward_days: float | None = Field(default=None)
    requires_approval: bool = Field(default=True)
    approval_levels: int = Field(default=1, ge=1, le=3)
    cancel_requires_approval: bool = Field(default=False)
    cancel_approval_levels: int = Field(default=1, ge=1, le=3)
    min_days_per_application: float = Field(default=0.5, ge=0)
    max_days_per_application: float | None = Field(default=None)
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
    # (days_per_year / 12). Only takes effect where no LeaveBucketPolicy
    # resolves for the employee — this is the zero-config fallback (see
    # leave/router.py::_resolve_entitlement); an explicit bucket policy's own
    # accrual_type/days_per_year wins when one applies.
    accrual_enabled: bool = Field(default=False)


class LeaveBalance(SQLModel, table=True):
    __tablename__ = "leave_balances"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

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
    last_accrued_period: str | None = Field(default=None, max_length=7)


class LeaveApplication(SQLModel, table=True):
    __tablename__ = "leave_applications"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    employment_id: UUID = Field(index=True)
    leave_type_id: UUID
    from_date: date
    to_date: date
    # Keyed "YYYY-MM" — one entry per calendar month the application touches,
    # matching leave_monthly_ledger's (calendar_year, calendar_month) grain
    # (a leave spanning a month boundary posts one engine transaction per key).
    days_by_month: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    document_id: UUID | None = Field(default=None)
    days_requested: float
    half_day_option: str = Field(default="NONE", max_length=15)
    reason: str | None = Field(default=None, max_length=1000)
    status: str = Field(default=LeaveApplicationStatus.DRAFT, max_length=25)
    current_level: int = Field(default=0)
    total_levels: int = Field(default=1)
    applied_at: datetime | None = Field(default=None)
    cancel_reason: str | None = Field(default=None, max_length=1000)
    cancel_requested_at: datetime | None = Field(default=None)


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
    notes: str | None = Field(default=None, max_length=500)
    granted_by: UUID | None = Field(default=None)
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
    notes: str | None = Field(default=None, max_length=500)
    processed_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now())


class LeaveApprovalAction(SQLModel, table=True):
    __tablename__ = "leave_approval_actions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    application_id: UUID = Field(index=True)
    action_type: str = Field(max_length=20)
    level: int
    # Exactly one of these identifies who acted. Employees/managers/HR have an
    # employment; a company-admin login with no employee record only has the account.
    approver_employment_id: UUID | None = Field(default=None)
    approver_user_account_id: UUID | None = Field(default=None)
    comments: str | None = Field(default=None, max_length=1000)
    actioned_at: datetime


class LeaveTransactionType(enum.StrEnum):
    OPENING = "OPENING"
    ACCRUAL = "ACCRUAL"
    GRANT = "GRANT"
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    LEAVE_TAKEN = "LEAVE_TAKEN"
    LEAVE_REVERSED = "LEAVE_REVERSED"
    ADJUSTMENT = "ADJUSTMENT"
    LAPSE = "LAPSE"
    ENCASHMENT = "ENCASHMENT"
    CARRY_FORWARD = "CARRY_FORWARD"


class LeaveBalanceBucket(SQLModel, table=True):
    __tablename__ = "leave_balance_buckets"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    name: str = Field(max_length=100)
    code: str = Field(max_length=20)
    is_unlimited: bool = Field(default=False)
    is_active: bool = Field(default=True)


class LeaveTypeBucketMapping(SQLModel, table=True):
    __tablename__ = "leave_type_bucket_mapping"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    leave_type_id: UUID = Field(index=True)
    bucket_id: UUID = Field(index=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)


class LeavePolicySet(SQLModel, table=True):
    __tablename__ = "leave_policy_sets"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_default: bool = Field(default=False)


class LeaveBucketPolicy(SQLModel, table=True):
    __tablename__ = "leave_bucket_policies"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    policy_set_id: UUID = Field(index=True)
    bucket_id: UUID = Field(index=True)

    accrual_type: str = Field(max_length=20)  # ANNUAL_UPFRONT, MONTHLY_PRORATE, NONE
    days_per_year: float = Field(ge=0)
    carry_forward_enabled: bool = Field(default=False)
    max_carry_forward_days: float | None = Field(default=None, ge=0)
    lapse_enabled: bool = Field(default=True)
    encashment_enabled: bool = Field(default=False)
    max_encashment_days: float | None = Field(default=None, ge=0)
    probation_eligible: bool = Field(default=False)
    min_service_months: int = Field(default=0, ge=0)
    pro_rate_first_year: bool = Field(default=True)

    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)


class LeavePolicyAssignment(SQLModel, table=True):
    __tablename__ = "leave_policy_assignments"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    employment_id: UUID | None = Field(default=None, index=True)
    org_unit_id: UUID | None = Field(default=None, index=True)
    legal_entity_id: UUID | None = Field(default=None, index=True)
    leave_policy_set_id: UUID = Field(index=True)
    effective_from: date
    effective_to: date | None = Field(default=None)


class LeaveMonthlyLedger(SQLModel, table=True):
    __tablename__ = "leave_monthly_ledger"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)

    employment_id: UUID = Field(index=True)
    bucket_id: UUID = Field(index=True)
    calendar_year: int
    calendar_month: int = Field(ge=1, le=12)
    fy_year: int = Field(index=True)

    opening: float = Field(default=0.0)
    accrued: float = Field(default=0.0)
    granted: float = Field(default=0.0)
    held: float = Field(default=0.0)
    adjustment: float = Field(default=0.0)
    taken: float = Field(default=0.0)
    lapsed: float = Field(default=0.0)
    encashed: float = Field(default=0.0)
    closing: float = Field(default=0.0)


class LeaveBalanceTransaction(SQLModel, table=True):
    __tablename__ = "leave_balance_transactions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    bucket_id: UUID = Field(index=True)
    leave_type_id: UUID | None = Field(default=None, index=True)

    transaction_type: str = Field(max_length=20)
    quantity: float
    previous_balance: float
    new_balance: float
    effective_date: date
    reason: str | None = Field(default=None, max_length=500)
    reference_id: UUID | None = Field(default=None)
    reference_type: str | None = Field(default=None, max_length=30)
    recorded_by: UUID
    approved_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

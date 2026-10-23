from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from hrms.core.versioning import version_field

AccrualType = Literal["ANNUAL_UPFRONT", "MONTHLY_PRORATE", "NONE"]


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
    apply_sandwich_rule: bool = False


class LeaveTypeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=10)
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
    apply_sandwich_rule: bool | None = None
    version: int | None = version_field()


class LeaveTypeResponse(LeaveTypeCreate):
    id: str
    is_active: bool
    version: int = 0


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
    probation_locked: bool = False
    unlock_date: date | None = None
    unlock_message: str | None = None


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


class LeaveBalanceAdjustmentRequest(BaseModel):
    employment_id: str = Field(
        description="Employee being adjusted — an HR/admin action, not self-service"
    )
    leave_type_id: str
    quantity: float = Field(description="Positive to add days, negative to remove")
    effective_date: date | None = None
    reason: str = Field(min_length=1, max_length=500)
    kind: Literal["OPENING", "ADJUSTMENT"] = "ADJUSTMENT"

    @model_validator(mode="after")
    def validate_quantity(self):
        if self.quantity == 0:
            raise ValueError("quantity must not be zero")
        return self


class LeaveBalanceAdjustmentResponse(BaseModel):
    employment_id: str
    leave_type_id: str
    leave_type_name: str
    kind: str
    quantity: float
    new_balance: float
    effective_date: date
    reason: str


class AccrualRunResponse(BaseModel):
    period: str
    balances_credited: int
    days_credited_total: float


class YearEndCloseResponse(BaseModel):
    fy_year: int
    buckets_closed: int
    days_lapsed: float


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


class LeaveTypeDays(BaseModel):
    leave_type_id: str
    name: str
    color: str
    days: float


class LeaveApplicationSummary(BaseModel):
    """Counts for everyone in the caller's scope — for dashboards, without fetching the list."""

    by_status: dict[str, int]
    # Approved days per leave type ("days taken").
    approved_days_by_type: list[LeaveTypeDays]


# ─── Balance Buckets ──────────────────────────────────────────────────────────


class LeaveBalanceBucketCreate(BaseModel):
    name: str = Field(max_length=100)
    code: str = Field(max_length=20)
    is_unlimited: bool = False


class LeaveBalanceBucketUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    version: int | None = version_field()


class LeaveBalanceBucketResponse(BaseModel):
    id: str
    name: str
    code: str
    is_unlimited: bool
    is_active: bool
    version: int = 0


# ─── Type-to-Bucket Mapping ───────────────────────────────────────────────────


class LeaveTypeBucketMappingCreate(BaseModel):
    leave_type_id: str
    bucket_id: str


class LeaveTypeBucketMappingResponse(BaseModel):
    id: str
    leave_type_id: str
    leave_type_name: str
    leave_type_code: str
    bucket_id: str
    bucket_name: str
    bucket_code: str


# ─── Leave Policy Sets ────────────────────────────────────────────────────────


class LeavePolicySetCreate(BaseModel):
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_default: bool = False


class LeavePolicySetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_default: bool | None = None
    version: int | None = version_field()


class LeavePolicySetResponse(BaseModel):
    id: str
    name: str
    description: str | None
    is_default: bool
    version: int = 0


# ─── Leave Bucket Policies ────────────────────────────────────────────────────


class LeaveBucketPolicyCreate(BaseModel):
    bucket_id: str
    accrual_type: AccrualType
    days_per_year: float = Field(ge=0)
    carry_forward_enabled: bool = False
    max_carry_forward_days: float | None = Field(default=None, ge=0)
    lapse_enabled: bool = True
    encashment_enabled: bool = False
    max_encashment_days: float | None = Field(default=None, ge=0)
    probation_eligible: bool = False
    min_service_months: int = Field(default=0, ge=0)
    pro_rate_first_year: bool = True
    apply_sandwich_rule: bool = False


class LeaveBucketPolicyUpdate(BaseModel):
    accrual_type: AccrualType | None = None
    days_per_year: float | None = Field(default=None, ge=0)
    carry_forward_enabled: bool | None = None
    max_carry_forward_days: float | None = Field(default=None, ge=0)
    lapse_enabled: bool | None = None
    encashment_enabled: bool | None = None
    max_encashment_days: float | None = Field(default=None, ge=0)
    probation_eligible: bool | None = None
    min_service_months: int | None = Field(default=None, ge=0)
    pro_rate_first_year: bool | None = None
    apply_sandwich_rule: bool | None = None
    version: int | None = version_field()


class LeaveBucketPolicyResponse(BaseModel):
    id: str
    policy_set_id: str
    bucket_id: str
    bucket_name: str
    bucket_code: str
    accrual_type: str
    days_per_year: float
    carry_forward_enabled: bool
    max_carry_forward_days: float | None
    lapse_enabled: bool
    encashment_enabled: bool
    max_encashment_days: float | None
    probation_eligible: bool
    min_service_months: int
    pro_rate_first_year: bool
    apply_sandwich_rule: bool = False
    version: int = 0


# ─── Leave Policy Assignments ─────────────────────────────────────────────────


class LeavePolicyAssignmentCreate(BaseModel):
    leave_policy_set_id: str
    effective_from: date
    effective_to: date | None = None
    employment_id: str | None = None
    org_unit_id: str | None = None
    legal_entity_id: str | None = None

    @model_validator(mode="after")
    def validate_targets(self):
        targets = [self.employment_id, self.org_unit_id, self.legal_entity_id]
        non_nulls = sum(1 for t in targets if t is not None)
        if non_nulls != 1:
            raise ValueError(
                "Exactly one of employment_id, org_unit_id, or legal_entity_id must be provided"
            )
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class LeavePolicyAssignmentResponse(BaseModel):
    id: str
    leave_policy_set_id: str
    leave_policy_set_name: str
    effective_from: date
    effective_to: date | None
    employment_id: str | None
    org_unit_id: str | None
    legal_entity_id: str | None


# ─── Ledger & Transactions Responses ──────────────────────────────────────────


class LeaveMonthlyLedgerResponse(BaseModel):
    id: str
    employment_id: str
    bucket_id: str
    bucket_name: str
    bucket_code: str
    calendar_year: int
    calendar_month: int
    fy_year: int
    opening: float
    accrued: float
    granted: float
    held: float
    adjustment: float
    taken: float
    lapsed: float
    encashed: float
    closing: float
    available: float


class LeaveBalanceTransactionResponse(BaseModel):
    id: str
    employment_id: str
    bucket_id: str
    bucket_name: str
    bucket_code: str
    leave_type_id: str | None
    leave_type_name: str | None
    leave_type_code: str | None
    transaction_type: str
    quantity: float
    previous_balance: float
    new_balance: float
    effective_date: date
    reason: str | None
    reference_id: str | None
    reference_type: str | None
    recorded_by: str
    approved_by: str | None
    recorded_at: datetime


# ─── Unified 1-Screen Policy Schemas ──────────────────────────────────────────


class UnifiedLeavePolicyRequest(BaseModel):
    name: str = Field(max_length=100)
    code: str | None = Field(default=None, max_length=10)
    days_per_year: float = Field(ge=0)
    accrual_type: AccrualType = "ANNUAL_UPFRONT"
    org_unit_id: str | None = None
    apply_sandwich_rule: bool = False
    probation_eligible: bool = False
    carry_forward: bool = False
    max_carry_forward_days: float | None = Field(default=None, ge=0)
    encashable: bool = False
    color: str = "#3B82F6"


class UnifiedLeavePolicyResponse(BaseModel):
    id: str
    leave_type_id: str
    name: str
    code: str
    days_per_year: float
    accrual_type: str
    org_unit_id: str | None = None
    org_unit_name: str | None = None
    apply_sandwich_rule: bool = False
    probation_eligible: bool = False
    carry_forward: bool = False
    max_carry_forward_days: float | None = None
    encashable: bool = False
    color: str = "#3B82F6"
    employees_covered: int = 0

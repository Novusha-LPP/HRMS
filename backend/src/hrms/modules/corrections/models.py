from __future__ import annotations

import enum
from datetime import date, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class CorrectionType(enum.StrEnum):
    PUNCH_IN = "PUNCH_IN"
    PUNCH_OUT = "PUNCH_OUT"
    MISSED_PUNCH = "MISSED_PUNCH"
    REGULARIZE = "REGULARIZE"
    MARK_PRESENT = "MARK_PRESENT"
    MARK_ABSENT = "MARK_ABSENT"
    LATE_REASON = "LATE_REASON"
    EARLY_DEPARTURE_REASON = "EARLY_DEPARTURE_REASON"


class CorrectionStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_L1 = "PENDING_L1"
    PENDING_L2 = "PENDING_L2"
    PENDING_L3 = "PENDING_L3"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AttendanceCorrectionRequest(SQLModel, table=True):
    __tablename__ = "attendance_correction_requests"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    employment_id: UUID = Field(index=True)
    work_date: date = Field(index=True)
    correction_type: str = Field(max_length=30)
    requested_punch_in: datetime | None = Field(default=None)
    requested_punch_out: datetime | None = Field(default=None)
    reason: str = Field(max_length=1000)
    status: str = Field(default=CorrectionStatus.DRAFT, max_length=20)
    current_level: int = Field(default=0)
    total_levels: int = Field(default=1)
    submitted_at: datetime | None = Field(default=None)


class CorrectionApprovalAction(SQLModel, table=True):
    __tablename__ = "correction_approval_actions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: datetime | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

    correction_id: UUID = Field(index=True)
    action: str = Field(max_length=10)
    level: int
    # Exactly one of these identifies who acted. Employees/managers/HR have an
    # employment; a company-admin login with no employee record only has the account.
    approver_employment_id: UUID | None = Field(default=None)
    approver_user_account_id: UUID | None = Field(default=None)
    comments: str | None = Field(default=None, max_length=1000)
    actioned_at: datetime

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class CorrectionType(str, enum.Enum):
    PUNCH_IN = "PUNCH_IN"
    PUNCH_OUT = "PUNCH_OUT"
    MISSED_PUNCH = "MISSED_PUNCH"
    REGULARIZE = "REGULARIZE"
    MARK_PRESENT = "MARK_PRESENT"
    MARK_ABSENT = "MARK_ABSENT"
    LATE_REASON = "LATE_REASON"
    EARLY_DEPARTURE_REASON = "EARLY_DEPARTURE_REASON"


class CorrectionStatus(str, enum.Enum):
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
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    employment_id: UUID = Field(index=True)
    work_date: date = Field(index=True)
    correction_type: str = Field(max_length=30)
    requested_punch_in: Optional[datetime] = Field(default=None)
    requested_punch_out: Optional[datetime] = Field(default=None)
    reason: str = Field(max_length=1000)
    status: str = Field(default=CorrectionStatus.DRAFT, max_length=20)
    current_level: int = Field(default=0)
    total_levels: int = Field(default=1)
    submitted_at: Optional[datetime] = Field(default=None)


class CorrectionApprovalAction(SQLModel, table=True):
    __tablename__ = "correction_approval_actions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    correction_id: UUID = Field(index=True)
    action: str = Field(max_length=10)
    level: int
    approver_employment_id: Optional[UUID] = Field(default=None)
    comments: Optional[str] = Field(default=None, max_length=1000)
    actioned_at: datetime

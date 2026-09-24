from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CorrectionCreateRequest(BaseModel):
    work_date: date
    correction_type: str
    requested_punch_in: Optional[datetime] = None
    requested_punch_out: Optional[datetime] = None
    reason: str


class CorrectionApprovalRequest(BaseModel):
    action: str  # APPROVE or REJECT
    comments: Optional[str] = None


class CorrectionApprovalActionResponse(BaseModel):
    id: str
    correction_id: str
    action: str
    level: int
    approver_employment_id: Optional[str]
    comments: Optional[str]
    actioned_at: datetime


class CorrectionResponse(BaseModel):
    id: str
    employment_id: str
    work_date: date
    correction_type: str
    requested_punch_in: Optional[datetime]
    requested_punch_out: Optional[datetime]
    reason: str
    status: str
    current_level: int
    total_levels: int
    submitted_at: Optional[datetime]
    approval_history: list[CorrectionApprovalActionResponse] = []

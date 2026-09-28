from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from hrms.modules.corrections.models import CorrectionType


class CorrectionCreateRequest(BaseModel):
    work_date: date
    correction_type: CorrectionType
    requested_punch_in: datetime | None = None
    requested_punch_out: datetime | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("requested_punch_in", "requested_punch_out")
    @classmethod
    def _must_be_an_instant(cls, v: datetime | None) -> datetime | None:
        # A bare "2026-09-27T09:00:00" has no timezone, so it would be stored as the wrong
        # moment (or fail at the database). Ask the client to say which instant it means.
        if v is not None and v.tzinfo is None:
            raise ValueError("must include a timezone offset, e.g. 2026-09-27T09:00:00+05:30")
        return v

    @model_validator(mode="after")
    def validate_punches(self):
        if (
            self.requested_punch_in
            and self.requested_punch_out
            and self.requested_punch_out <= self.requested_punch_in
        ):
            raise ValueError("Punch OUT must follow punch IN")
        if self.correction_type == "PUNCH_IN" and not self.requested_punch_in:
            raise ValueError("Punch IN is required")
        if self.correction_type == "PUNCH_OUT" and not self.requested_punch_out:
            raise ValueError("Punch OUT is required")
        if self.correction_type in ("MARK_PRESENT", "REGULARIZE") and not (
            self.requested_punch_in and self.requested_punch_out
        ):
            raise ValueError("Both punches are required")
        if self.correction_type == "MISSED_PUNCH" and not (
            self.requested_punch_in or self.requested_punch_out
        ):
            raise ValueError("Supply the missing punch")
        return self


class CorrectionApprovalRequest(BaseModel):
    action: str  # APPROVE or REJECT
    comments: str | None = None


class CorrectionApprovalActionResponse(BaseModel):
    id: str
    correction_id: str
    action: str
    level: int
    approver_employment_id: str | None
    comments: str | None
    actioned_at: datetime


class CorrectionResponse(BaseModel):
    id: str
    employment_id: str
    work_date: date
    correction_type: str
    requested_punch_in: datetime | None
    requested_punch_out: datetime | None
    reason: str
    status: str
    current_level: int
    total_levels: int
    submitted_at: datetime | None
    approval_history: list[CorrectionApprovalActionResponse] = []

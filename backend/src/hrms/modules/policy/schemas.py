from __future__ import annotations

from datetime import date, time
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class PolicyTemplateCreate(BaseModel):
    name: str = Field(max_length=100)
    description: Optional[str] = None
    is_default: bool = False
    timezone: str = "UTC"
    expected_start_time: time = time(9, 0)
    expected_end_time: time = time(18, 0)
    work_days: str = Field(default="1111100", max_length=7)
    saturday_pattern: Literal["ALL", "SECOND_FOURTH_OFF", "FIRST_THIRD_OFF"] = "ALL"
    break_minutes: int = Field(default=60, ge=0)
    break_auto_deduct: bool = False
    grace_late_minutes: int = Field(default=0, ge=0)
    grace_early_departure_minutes: int = Field(default=0, ge=0)
    half_day_threshold_pct: int = Field(default=50, ge=1, le=100)
    ot_enabled: bool = True
    ot_qualifying_minutes: int = Field(default=30, ge=0)
    ot_rate: float = Field(default=1.5, ge=1.0)
    ot_daily_cap_minutes: Optional[int] = None
    punch_rounding_minutes: int = Field(default=0, ge=0)
    punch_rounding_direction: str = "NONE"
    correction_requires_approval: bool = True
    correction_approval_levels: int = Field(default=1, ge=1, le=3)


class PolicyTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    timezone: Optional[str] = None
    expected_start_time: Optional[time] = None
    expected_end_time: Optional[time] = None
    work_days: Optional[str] = None
    saturday_pattern: Optional[Literal["ALL", "SECOND_FOURTH_OFF", "FIRST_THIRD_OFF"]] = None
    break_minutes: Optional[int] = None
    break_auto_deduct: Optional[bool] = None
    grace_late_minutes: Optional[int] = None
    grace_early_departure_minutes: Optional[int] = None
    half_day_threshold_pct: Optional[int] = None
    ot_enabled: Optional[bool] = None
    ot_qualifying_minutes: Optional[int] = None
    ot_rate: Optional[float] = None
    ot_daily_cap_minutes: Optional[int] = None
    punch_rounding_minutes: Optional[int] = None
    punch_rounding_direction: Optional[str] = None
    correction_requires_approval: Optional[bool] = None
    correction_approval_levels: Optional[int] = None


class PolicyTemplateResponse(PolicyTemplateCreate):
    id: str
    standard_minutes: int


class EmployeePolicyAssignCreate(BaseModel):
    # Exactly one of employment_id / org_unit_id / legal_entity_id — an
    # employee-level assignment, a department-wide one (applies to everyone
    # currently assigned to that org unit and its sub-units without their
    # own override), or a company-wide one (applies to everyone in that
    # legal entity without a more specific override) — see
    # policy/engine.py:resolve_policy for the priority order.
    employment_id: Optional[str] = None
    org_unit_id: Optional[str] = None
    legal_entity_id: Optional[str] = None
    policy_template_id: str
    effective_from: date
    effective_to: Optional[date] = None
    ot_qualifying_minutes_override: Optional[int] = None
    grace_late_minutes_override: Optional[int] = None
    grace_early_departure_minutes_override: Optional[int] = None
    ot_enabled_override: Optional[bool] = None
    ot_rate_override: Optional[float] = None

    @model_validator(mode="after")
    def _exactly_one_target(self):
        if sum(bool(v) for v in (self.employment_id, self.org_unit_id, self.legal_entity_id)) != 1:
            raise ValueError("Provide exactly one of employment_id, org_unit_id or legal_entity_id")
        return self


class EmployeePolicyAssignResponse(EmployeePolicyAssignCreate):
    id: str
    policy_template_name: Optional[str] = None
    org_unit_name: Optional[str] = None
    legal_entity_name: Optional[str] = None

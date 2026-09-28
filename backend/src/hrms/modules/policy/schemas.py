from __future__ import annotations

from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PolicyTemplateCreate(BaseModel):
    name: str = Field(max_length=100)
    description: str | None = None
    is_default: bool = False
    timezone: str = "UTC"
    expected_start_time: time = time(9, 0)
    expected_end_time: time = time(18, 0)
    work_days: str = Field(default="1111100", pattern="^[01]{7}$")
    saturday_pattern: Literal["ALL", "SECOND_FOURTH_OFF", "FIRST_THIRD_OFF"] = "ALL"
    break_minutes: int = Field(default=60, ge=0)
    break_auto_deduct: bool = False
    grace_late_minutes: int = Field(default=0, ge=0)
    grace_early_departure_minutes: int = Field(default=0, ge=0)
    half_day_threshold_pct: int = Field(default=50, ge=1, le=100)
    ot_enabled: bool = True
    ot_qualifying_minutes: int = Field(default=30, ge=0)
    ot_rate: float = Field(default=1.5, ge=1.0)
    ot_daily_cap_minutes: int | None = Field(default=None, ge=0)
    punch_rounding_minutes: int = Field(default=0, ge=0)
    punch_rounding_direction: Literal["NONE", "UP", "DOWN", "NEAREST"] = "NONE"
    correction_requires_approval: bool = True
    correction_approval_levels: int = Field(default=1, ge=1, le=3)


class PolicyTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None
    timezone: str | None = None
    expected_start_time: time | None = None
    expected_end_time: time | None = None
    work_days: str | None = Field(default=None, pattern="^[01]{7}$")
    saturday_pattern: Literal["ALL", "SECOND_FOURTH_OFF", "FIRST_THIRD_OFF"] | None = None
    break_minutes: int | None = Field(default=None, ge=0)
    break_auto_deduct: bool | None = None
    grace_late_minutes: int | None = Field(default=None, ge=0)
    grace_early_departure_minutes: int | None = Field(default=None, ge=0)
    half_day_threshold_pct: int | None = Field(default=None, ge=1, le=100)
    ot_enabled: bool | None = None
    ot_qualifying_minutes: int | None = Field(default=None, ge=0)
    ot_rate: float | None = None
    ot_daily_cap_minutes: int | None = Field(default=None, ge=0)
    punch_rounding_minutes: int | None = Field(default=None, ge=0)
    punch_rounding_direction: Literal["NONE", "UP", "DOWN", "NEAREST"] | None = None
    correction_requires_approval: bool | None = None
    correction_approval_levels: int | None = Field(default=None, ge=1, le=3)


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
    employment_id: str | None = None
    org_unit_id: str | None = None
    legal_entity_id: str | None = None
    policy_template_id: str
    effective_from: date
    effective_to: date | None = None
    ot_qualifying_minutes_override: int | None = Field(default=None, ge=0)
    grace_late_minutes_override: int | None = Field(default=None, ge=0)
    grace_early_departure_minutes_override: int | None = Field(default=None, ge=0)
    ot_enabled_override: bool | None = None
    ot_rate_override: float | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self):
        if sum(bool(v) for v in (self.employment_id, self.org_unit_id, self.legal_entity_id)) != 1:
            raise ValueError("Provide exactly one of employment_id, org_unit_id or legal_entity_id")
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Policy end date must not precede its start")
        return self


class EmployeePolicyAssignResponse(EmployeePolicyAssignCreate):
    id: str
    policy_template_name: str | None = None
    org_unit_name: str | None = None
    legal_entity_name: str | None = None

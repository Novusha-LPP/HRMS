from __future__ import annotations

from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field


class PolicyTemplateCreate(BaseModel):
    name: str = Field(max_length=100)
    description: Optional[str] = None
    is_default: bool = False
    timezone: str = "UTC"
    expected_start_time: time = time(9, 0)
    expected_end_time: time = time(18, 0)
    work_days: str = Field(default="1111100", max_length=7)
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
    employment_id: str
    policy_template_id: str
    effective_from: date
    effective_to: Optional[date] = None
    ot_qualifying_minutes_override: Optional[int] = None
    grace_late_minutes_override: Optional[int] = None
    grace_early_departure_minutes_override: Optional[int] = None
    ot_enabled_override: Optional[bool] = None
    ot_rate_override: Optional[float] = None


class EmployeePolicyAssignResponse(EmployeePolicyAssignCreate):
    id: str
    policy_template_name: Optional[str] = None

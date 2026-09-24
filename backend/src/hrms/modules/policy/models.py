from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class PolicyTemplate(SQLModel, table=True):
    __tablename__ = "policy_templates"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    name: str = Field(max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    is_default: bool = Field(default=False)
    timezone: str = Field(default="UTC", max_length=50)

    expected_start_time: time = Field(default=time(9, 0))
    expected_end_time: time = Field(default=time(18, 0))
    work_days: str = Field(default="1111100", max_length=7)
    break_minutes: int = Field(default=60, ge=0)
    break_auto_deduct: bool = Field(default=False)

    grace_late_minutes: int = Field(default=0, ge=0)
    grace_early_departure_minutes: int = Field(default=0, ge=0)
    half_day_threshold_pct: int = Field(default=50, ge=1, le=100)

    ot_enabled: bool = Field(default=True)
    ot_qualifying_minutes: int = Field(default=30, ge=0)
    ot_rate: float = Field(default=1.5, ge=1.0)
    ot_daily_cap_minutes: Optional[int] = Field(default=None)

    punch_rounding_minutes: int = Field(default=0, ge=0)
    punch_rounding_direction: str = Field(default="NONE", max_length=10)

    correction_requires_approval: bool = Field(default=True)
    correction_approval_levels: int = Field(default=1, ge=1, le=3)


class EmployeePolicyAssignment(SQLModel, table=True):
    __tablename__ = "employee_policy_assignments"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    employment_id: UUID = Field(index=True)
    policy_template_id: UUID = Field(index=True)
    effective_from: date
    effective_to: Optional[date] = Field(default=None)

    ot_qualifying_minutes_override: Optional[int] = Field(default=None)
    grace_late_minutes_override: Optional[int] = Field(default=None)
    grace_early_departure_minutes_override: Optional[int] = Field(default=None)
    ot_enabled_override: Optional[bool] = Field(default=None)
    ot_rate_override: Optional[float] = Field(default=None)

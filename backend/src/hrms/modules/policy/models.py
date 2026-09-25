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
    # Only consulted for Saturday (work_days index 5), named by which
    # Saturdays are OFF: ALL = no alternation; SECOND_FOURTH_OFF /
    # FIRST_THIRD_OFF = those two Saturdays are off, every other Saturday
    # (including a 5th, when a month has one) works. To stop Saturday from
    # ever being a working day, turn it off in work_days directly instead
    # of using this field. See core.datetime_utils.is_working_day.
    saturday_pattern: str = Field(default="ALL", max_length=20)
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
    """
    A policy assignment targets exactly one of employment_id, org_unit_id or
    legal_entity_id (never more than one, never none — enforced by a DB
    check constraint and by the request schema). resolve_policy() checks
    employee-level rows first, then walks up the employee's department's
    ancestor chain (org_unit_id rows), then the employee's legal entity
    (legal_entity_id rows — this is the "whole company" tier: unlike
    org_unit_id, a legal entity is guaranteed to exist for every employee
    even if no org_unit tree has been set up yet), then falls back to the
    tenant default template.
    """
    __tablename__ = "employee_policy_assignments"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    recorded_at: Optional[datetime] = Field(default=None)
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

    employment_id: Optional[UUID] = Field(default=None, index=True)
    org_unit_id: Optional[UUID] = Field(default=None, index=True)
    legal_entity_id: Optional[UUID] = Field(default=None, index=True)
    policy_template_id: UUID = Field(index=True)
    effective_from: date
    effective_to: Optional[date] = Field(default=None)

    ot_qualifying_minutes_override: Optional[int] = Field(default=None)
    grace_late_minutes_override: Optional[int] = Field(default=None)
    grace_early_departure_minutes_override: Optional[int] = Field(default=None)
    ot_enabled_override: Optional[bool] = Field(default=None)
    ot_rate_override: Optional[float] = Field(default=None)

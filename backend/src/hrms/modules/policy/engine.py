"""
Policy resolution engine.

resolve_policy(employment_id, work_date, session, tenant_id) → ResolvedPolicy

Looks up the active EmployeePolicyAssignment for the employee on the given date,
merges per-employee overrides onto the template, and returns a ResolvedPolicy
dataclass ready for use by the attendance computation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlmodel import select

from hrms.core.datetime_utils import compute_standard_minutes
from hrms.modules.policy.models import EmployeePolicyAssignment, PolicyTemplate


@dataclass
class ResolvedPolicy:
    """Fully merged policy ready for calculations — no further DB lookups needed."""
    timezone: str
    expected_start_time: time
    expected_end_time: time
    work_days: str
    saturday_pattern: str
    break_minutes: int
    break_auto_deduct: bool
    standard_minutes: int  # derived from start/end/break
    grace_late_minutes: int
    grace_early_departure_minutes: int
    half_day_threshold_pct: int
    ot_enabled: bool
    ot_qualifying_minutes: int
    ot_rate: float
    ot_daily_cap_minutes: Optional[int]
    punch_rounding_minutes: int
    punch_rounding_direction: str
    correction_requires_approval: bool
    correction_approval_levels: int


_DEFAULT_POLICY = ResolvedPolicy(
    timezone="UTC",
    expected_start_time=time(9, 0),
    expected_end_time=time(18, 0),
    work_days="1111100",
    saturday_pattern="ALL",
    break_minutes=60,
    break_auto_deduct=False,
    standard_minutes=480,
    grace_late_minutes=0,
    grace_early_departure_minutes=0,
    half_day_threshold_pct=50,
    ot_enabled=False,
    ot_qualifying_minutes=30,
    ot_rate=1.5,
    ot_daily_cap_minutes=None,
    punch_rounding_minutes=0,
    punch_rounding_direction="NONE",
    correction_requires_approval=True,
    correction_approval_levels=1,
)


def _merge(template: PolicyTemplate, assignment: EmployeePolicyAssignment) -> ResolvedPolicy:
    """Apply per-employee overrides on top of the template."""
    ot_enabled = (
        assignment.ot_enabled_override
        if assignment.ot_enabled_override is not None
        else template.ot_enabled
    )
    ot_qualifying = (
        assignment.ot_qualifying_minutes_override
        if assignment.ot_qualifying_minutes_override is not None
        else template.ot_qualifying_minutes
    )
    grace_late = (
        assignment.grace_late_minutes_override
        if assignment.grace_late_minutes_override is not None
        else template.grace_late_minutes
    )
    grace_early = (
        assignment.grace_early_departure_minutes_override
        if assignment.grace_early_departure_minutes_override is not None
        else template.grace_early_departure_minutes
    )
    ot_rate = (
        assignment.ot_rate_override
        if assignment.ot_rate_override is not None
        else template.ot_rate
    )
    std_mins = compute_standard_minutes(
        template.expected_start_time, template.expected_end_time, template.break_minutes
    )
    return ResolvedPolicy(
        timezone=template.timezone,
        expected_start_time=template.expected_start_time,
        expected_end_time=template.expected_end_time,
        work_days=template.work_days,
        saturday_pattern=template.saturday_pattern,
        break_minutes=template.break_minutes,
        break_auto_deduct=template.break_auto_deduct,
        standard_minutes=std_mins,
        grace_late_minutes=grace_late,
        grace_early_departure_minutes=grace_early,
        half_day_threshold_pct=template.half_day_threshold_pct,
        ot_enabled=ot_enabled,
        ot_qualifying_minutes=ot_qualifying,
        ot_rate=ot_rate,
        ot_daily_cap_minutes=template.ot_daily_cap_minutes,
        punch_rounding_minutes=template.punch_rounding_minutes,
        punch_rounding_direction=template.punch_rounding_direction,
        correction_requires_approval=template.correction_requires_approval,
        correction_approval_levels=template.correction_approval_levels,
    )


async def _resolve_department_assignment(
    session, tenant_id: UUID, employment_id: UUID, work_date: date,
) -> EmployeePolicyAssignment | None:
    """
    An employee's department-level policy, if any: find their current
    org_unit, then walk up its ancestor chain (self first) for the nearest
    org_unit with an active policy assignment. Mirrors the recursive
    ancestor walk core.authz._entities_for_org_units already does for
    role scopes.
    """
    org_unit_row = await session.execute(
        text("""
            SELECT org_unit_id FROM assignments
            WHERE tenant_id = CAST(:tid AS uuid) AND employment_id = CAST(:eid AS uuid)
              AND effective_to IS NULL
            LIMIT 1
        """),
        {"tid": str(tenant_id), "eid": str(employment_id)},
    )
    org_unit_id = org_unit_row.scalar()
    if org_unit_id is None:
        return None

    match_row = await session.execute(
        text("""
            WITH RECURSIVE chain AS (
                SELECT id, parent_id, 0 AS depth
                FROM org_units
                WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:start AS uuid)
                UNION ALL
                SELECT ou.id, ou.parent_id, chain.depth + 1
                FROM org_units ou
                JOIN chain ON ou.id = chain.parent_id
                WHERE ou.tenant_id = CAST(:tid AS uuid)
            )
            SELECT epa.id
            FROM employee_policy_assignments epa
            JOIN chain ON chain.id = epa.org_unit_id
            WHERE epa.tenant_id = CAST(:tid AS uuid)
              AND epa.effective_from <= CAST(:work_date AS date)
              AND (epa.effective_to IS NULL OR epa.effective_to >= CAST(:work_date AS date))
              AND epa.archived_at IS NULL
            ORDER BY chain.depth ASC, epa.effective_from DESC
            LIMIT 1
        """),
        {"tid": str(tenant_id), "start": str(org_unit_id), "work_date": work_date},
    )
    match_id = match_row.scalar()
    if match_id is None:
        return None

    row = await session.execute(
        select(EmployeePolicyAssignment)
        .where(EmployeePolicyAssignment.tenant_id == tenant_id)
        .where(EmployeePolicyAssignment.id == match_id)
    )
    return row.scalars().first()


async def _resolve_legal_entity_assignment(
    session, tenant_id: UUID, employment_id: UUID, work_date: date,
) -> EmployeePolicyAssignment | None:
    """
    An employee's company-wide policy, if any. Unlike org_unit_id, every
    employment always has a legal_entity_id (set at hire, on the
    employments table directly) — so this tier works even for a tenant
    that hasn't built out an org_unit tree at all, which org_unit_id-based
    department assignment can't guarantee.
    """
    entity_row = await session.execute(
        text("""
            SELECT legal_entity_id FROM employments
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:eid AS uuid)
        """),
        {"tid": str(tenant_id), "eid": str(employment_id)},
    )
    legal_entity_id = entity_row.scalar()
    if legal_entity_id is None:
        return None

    row = await session.execute(
        select(EmployeePolicyAssignment)
        .where(EmployeePolicyAssignment.tenant_id == tenant_id)
        .where(EmployeePolicyAssignment.legal_entity_id == legal_entity_id)
        .where(EmployeePolicyAssignment.effective_from <= work_date)
        .where(
            (EmployeePolicyAssignment.effective_to == None)  # noqa: E711
            | (EmployeePolicyAssignment.effective_to >= work_date)
        )
        .where(EmployeePolicyAssignment.archived_at == None)  # noqa: E711
        .order_by(EmployeePolicyAssignment.effective_from.desc())
        .limit(1)
    )
    return row.scalars().first()


async def resolve_policy(
    employment_id: UUID,
    work_date: date,
    session,
    tenant_id: UUID,
) -> ResolvedPolicy:
    """
    Return the resolved policy for an employee on a specific date.
    Priority: employee-specific assignment, then their department's
    assignment (walking up the org hierarchy), then their legal entity's
    (company-wide) assignment, then the tenant's default template, then
    hard-coded system defaults if none of those exist.
    """
    # Find active employee-specific assignment
    asgn_row = await session.execute(
        select(EmployeePolicyAssignment)
        .where(EmployeePolicyAssignment.tenant_id == tenant_id)
        .where(EmployeePolicyAssignment.employment_id == employment_id)
        .where(EmployeePolicyAssignment.effective_from <= work_date)
        .where(
            (EmployeePolicyAssignment.effective_to == None)  # noqa: E711
            | (EmployeePolicyAssignment.effective_to >= work_date)
        )
        .where(EmployeePolicyAssignment.archived_at == None)  # noqa: E711
        .order_by(EmployeePolicyAssignment.effective_from.desc())
        .limit(1)
    )
    assignment: EmployeePolicyAssignment | None = asgn_row.scalars().first()

    if assignment is None:
        assignment = await _resolve_department_assignment(session, tenant_id, employment_id, work_date)

    if assignment is None:
        assignment = await _resolve_legal_entity_assignment(session, tenant_id, employment_id, work_date)

    if assignment is None:
        # Try the tenant's default template
        tpl_row = await session.execute(
            select(PolicyTemplate)
            .where(PolicyTemplate.tenant_id == tenant_id)
            .where(PolicyTemplate.is_default == True)  # noqa: E712
            .where(PolicyTemplate.archived_at == None)  # noqa: E711
            .limit(1)
        )
        tpl = tpl_row.scalars().first()
        if tpl is None:
            return _DEFAULT_POLICY
        std_mins = compute_standard_minutes(tpl.expected_start_time, tpl.expected_end_time, tpl.break_minutes)
        return ResolvedPolicy(
            timezone=tpl.timezone,
            expected_start_time=tpl.expected_start_time,
            expected_end_time=tpl.expected_end_time,
            work_days=tpl.work_days,
            saturday_pattern=tpl.saturday_pattern,
            break_minutes=tpl.break_minutes,
            break_auto_deduct=tpl.break_auto_deduct,
            standard_minutes=std_mins,
            grace_late_minutes=tpl.grace_late_minutes,
            grace_early_departure_minutes=tpl.grace_early_departure_minutes,
            half_day_threshold_pct=tpl.half_day_threshold_pct,
            ot_enabled=tpl.ot_enabled,
            ot_qualifying_minutes=tpl.ot_qualifying_minutes,
            ot_rate=tpl.ot_rate,
            ot_daily_cap_minutes=tpl.ot_daily_cap_minutes,
            punch_rounding_minutes=tpl.punch_rounding_minutes,
            punch_rounding_direction=tpl.punch_rounding_direction,
            correction_requires_approval=tpl.correction_requires_approval,
            correction_approval_levels=tpl.correction_approval_levels,
        )

    # Load template for this assignment
    tpl_row = await session.execute(
        select(PolicyTemplate)
        .where(PolicyTemplate.tenant_id == tenant_id)
        .where(PolicyTemplate.id == assignment.policy_template_id)
    )
    template = tpl_row.scalars().first()
    if template is None:
        return _DEFAULT_POLICY

    return _merge(template, assignment)

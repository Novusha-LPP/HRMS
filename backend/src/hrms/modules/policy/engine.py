"""
Policy resolution engine.

resolve_policy(employment_id, work_date, session, tenant_id) → ResolvedPolicy

Looks up the active EmployeePolicyAssignment for the employee on the given date,
merges per-employee overrides onto the template, and returns a ResolvedPolicy
dataclass ready for use by the attendance computation helpers.

PolicyResolver answers the same question for many employees at once (daily
analysis, reports) with a handful of queries instead of ~8 per employee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from uuid import UUID

from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.config import settings
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
    ot_daily_cap_minutes: int | None
    punch_rounding_minutes: int
    punch_rounding_direction: str
    correction_requires_approval: bool
    correction_approval_levels: int


def default_policy() -> ResolvedPolicy:
    """
    The deployment's last-resort policy, used only when no template is assigned
    to the employee, their department, their company or their tenant. The
    values come from settings (HRMS_DEFAULT_TIMEZONE, HRMS_DEFAULT_WORK_START,
    ...) rather than being baked into the code, so they can differ per
    deployment; a tenant that needs different rules should define its own
    default template instead.
    """
    start = time.fromisoformat(settings.default_work_start)
    end = time.fromisoformat(settings.default_work_end)
    break_minutes = 60
    return ResolvedPolicy(
        timezone=settings.default_timezone,
        expected_start_time=start,
        expected_end_time=end,
        work_days="1111100",
        saturday_pattern="ALL",
        break_minutes=break_minutes,
        break_auto_deduct=False,
        standard_minutes=compute_standard_minutes(start, end, break_minutes),
        grace_late_minutes=settings.default_grace_late_minutes,
        grace_early_departure_minutes=settings.default_grace_early_minutes,
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


def _merge(template: PolicyTemplate, assignment: EmployeePolicyAssignment | None) -> ResolvedPolicy:
    """Apply per-employee overrides (if any) on top of the template."""

    def pick(override, base):
        return override if override is not None else base

    a = assignment
    return ResolvedPolicy(
        timezone=template.timezone,
        expected_start_time=template.expected_start_time,
        expected_end_time=template.expected_end_time,
        work_days=template.work_days,
        saturday_pattern=template.saturday_pattern,
        break_minutes=template.break_minutes,
        break_auto_deduct=template.break_auto_deduct,
        standard_minutes=compute_standard_minutes(
            template.expected_start_time, template.expected_end_time, template.break_minutes
        ),
        grace_late_minutes=pick(a and a.grace_late_minutes_override, template.grace_late_minutes),
        grace_early_departure_minutes=pick(
            a and a.grace_early_departure_minutes_override, template.grace_early_departure_minutes
        ),
        half_day_threshold_pct=template.half_day_threshold_pct,
        ot_enabled=pick(a and a.ot_enabled_override, template.ot_enabled),
        ot_qualifying_minutes=pick(
            a and a.ot_qualifying_minutes_override, template.ot_qualifying_minutes
        ),
        ot_rate=pick(a and a.ot_rate_override, template.ot_rate),
        ot_daily_cap_minutes=template.ot_daily_cap_minutes,
        punch_rounding_minutes=template.punch_rounding_minutes,
        punch_rounding_direction=template.punch_rounding_direction,
        correction_requires_approval=template.correction_requires_approval,
        correction_approval_levels=template.correction_approval_levels,
    )


async def _department_assignment_for_unit(
    session, tenant_id: UUID, org_unit_id: UUID, work_date: date
) -> EmployeePolicyAssignment | None:
    """
    The nearest active department-level policy assignment for an org unit,
    walking up its ancestor chain (the unit itself first). Mirrors the
    recursive ancestor walk core.authz already does for role scopes.
    """
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


async def _resolve_department_assignment(
    session,
    tenant_id: UUID,
    employment_id: UUID,
    work_date: date,
) -> EmployeePolicyAssignment | None:
    """An employee's department-level policy, if any (via their current org unit)."""
    org_unit_row = await session.execute(
        text("""
            SELECT org_unit_id FROM assignments
            WHERE tenant_id = CAST(:tid AS uuid) AND employment_id = CAST(:eid AS uuid)
              AND effective_from <= :work_date
              AND (effective_to IS NULL OR effective_to > :work_date)
            ORDER BY effective_from DESC LIMIT 1
        """),
        {"tid": str(tenant_id), "eid": str(employment_id), "work_date": work_date},
    )
    org_unit_id = org_unit_row.scalar()
    if org_unit_id is None:
        return None
    return await _department_assignment_for_unit(session, tenant_id, org_unit_id, work_date)


async def _entity_assignment(
    session, tenant_id: UUID, legal_entity_id: UUID, work_date: date
) -> EmployeePolicyAssignment | None:
    row = await session.execute(
        select(EmployeePolicyAssignment)
        .where(EmployeePolicyAssignment.tenant_id == tenant_id)
        .where(EmployeePolicyAssignment.legal_entity_id == legal_entity_id)
        .where(EmployeePolicyAssignment.effective_from <= work_date)
        .where(
            (col(EmployeePolicyAssignment.effective_to) == None)  # noqa: E711
            | (col(EmployeePolicyAssignment.effective_to) >= work_date)
        )
        .where(EmployeePolicyAssignment.archived_at == None)  # noqa: E711
        .order_by(col(EmployeePolicyAssignment.effective_from).desc())
        .limit(1)
    )
    return row.scalars().first()


async def _resolve_legal_entity_assignment(
    session,
    tenant_id: UUID,
    employment_id: UUID,
    work_date: date,
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
    return await _entity_assignment(session, tenant_id, legal_entity_id, work_date)


async def _policy_for(
    session, tenant_id: UUID, assignment: EmployeePolicyAssignment | None
) -> ResolvedPolicy:
    """Turn the winning assignment (or the lack of one) into a ResolvedPolicy."""
    if assignment is None:
        # The tenant's default template, else the deployment's fallback.
        tpl_row = await session.execute(
            select(PolicyTemplate)
            .where(PolicyTemplate.tenant_id == tenant_id)
            .where(PolicyTemplate.is_default == True)  # noqa: E712
            .where(PolicyTemplate.archived_at == None)  # noqa: E711
            .limit(1)
        )
        tpl = tpl_row.scalars().first()
        return default_policy() if tpl is None else _merge(tpl, None)

    tpl_row = await session.execute(
        select(PolicyTemplate)
        .where(PolicyTemplate.tenant_id == tenant_id)
        .where(PolicyTemplate.id == assignment.policy_template_id)
    )
    template = tpl_row.scalars().first()
    return default_policy() if template is None else _merge(template, assignment)


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
    the deployment's fallback (default_policy) if none of those exist.
    """
    # Find active employee-specific assignment
    asgn_row = await session.execute(
        select(EmployeePolicyAssignment)
        .where(EmployeePolicyAssignment.tenant_id == tenant_id)
        .where(EmployeePolicyAssignment.employment_id == employment_id)
        .where(EmployeePolicyAssignment.effective_from <= work_date)
        .where(
            (col(EmployeePolicyAssignment.effective_to) == None)  # noqa: E711
            | (col(EmployeePolicyAssignment.effective_to) >= work_date)
        )
        .where(EmployeePolicyAssignment.archived_at == None)  # noqa: E711
        .order_by(col(EmployeePolicyAssignment.effective_from).desc())
        .limit(1)
    )
    assignment: EmployeePolicyAssignment | None = asgn_row.scalars().first()

    if assignment is None:
        assignment = await _resolve_department_assignment(
            session, tenant_id, employment_id, work_date
        )

    if assignment is None:
        assignment = await _resolve_legal_entity_assignment(
            session, tenant_id, employment_id, work_date
        )

    return await _policy_for(session, tenant_id, assignment)


class PolicyResolver:
    """Resolve one date with three tenant-scoped reads, independent of employee/unit count."""

    def __init__(self, session, tenant_id: UUID, work_date: date) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._work_date = work_date
        self._loaded = False
        self._personal: dict[UUID, EmployeePolicyAssignment] = {}
        self._departments: dict[UUID, EmployeePolicyAssignment] = {}
        self._entities: dict[UUID, EmployeePolicyAssignment] = {}
        self._parents: dict[UUID, UUID | None] = {}
        self._templates: dict[UUID, PolicyTemplate] = {}
        self._default = default_policy()
        self._shared: dict[tuple[UUID | None, UUID | None], ResolvedPolicy] = {}

    async def _load(self) -> None:
        if self._loaded:
            return
        assignments = (
            await self._session.execute(
                select(EmployeePolicyAssignment)
                .where(EmployeePolicyAssignment.tenant_id == self._tenant_id)
                .where(EmployeePolicyAssignment.effective_from <= self._work_date)
                .where(
                    (col(EmployeePolicyAssignment.effective_to) == None)  # noqa: E711
                    | (col(EmployeePolicyAssignment.effective_to) >= self._work_date)
                )
                .where(EmployeePolicyAssignment.archived_at == None)  # noqa: E711
                .order_by(
                    col(EmployeePolicyAssignment.effective_from).desc(),
                    col(EmployeePolicyAssignment.id),
                )
            )
        ).scalars()
        for assignment in assignments:
            for attr, mapping in (
                ("employment_id", self._personal),
                ("org_unit_id", self._departments),
                ("legal_entity_id", self._entities),
            ):
                target = getattr(assignment, attr)
                if target is not None:
                    mapping.setdefault(target, assignment)
        templates = (
            await self._session.execute(
                select(PolicyTemplate).where(PolicyTemplate.tenant_id == self._tenant_id)
            )
        ).scalars()
        for template in templates:
            self._templates[template.id] = template
            if template.is_default and template.archived_at is None:
                self._default = _merge(template, None)
        self._parents = dict(
            (
                await self._session.execute(
                    text("SELECT id,parent_id FROM org_units WHERE tenant_id=:tid"),
                    {"tid": self._tenant_id},
                )
            ).all()
        )
        self._loaded = True

    def _resolved(self, assignment: EmployeePolicyAssignment | None) -> ResolvedPolicy:
        if assignment is None:
            return self._default
        template = self._templates.get(assignment.policy_template_id)
        return default_policy() if template is None else _merge(template, assignment)

    async def resolve(
        self, employment_id: UUID, *, org_unit_id: UUID | None, legal_entity_id: UUID | None
    ) -> ResolvedPolicy:
        await self._load()
        personal = self._personal.get(employment_id)
        if personal is not None:
            return self._resolved(personal)
        key = (org_unit_id, legal_entity_id)
        if key not in self._shared:
            assignment = None
            unit = org_unit_id
            visited: set[UUID] = set()
            while unit is not None:
                if unit in visited:
                    raise ValueError("Organization hierarchy contains a cycle")
                visited.add(unit)
                assignment = self._departments.get(unit)
                if assignment is not None:
                    break
                unit = self._parents.get(unit)
            if assignment is None and legal_entity_id is not None:
                assignment = self._entities.get(legal_entity_id)
            self._shared[key] = self._resolved(assignment)
        return self._shared[key]

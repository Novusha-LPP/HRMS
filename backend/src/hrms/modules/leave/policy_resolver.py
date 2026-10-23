"""
Leave policy resolution cascade:
Employee -> Department (org unit ancestor walk) -> Legal Entity -> Tenant Default.

Resolves the active LeavePolicySet, LeaveBucketPolicy, and Financial Year calendar
for an employee on any given date.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from hrms.core.config import settings
from hrms.core.org_hierarchy import (
    get_employment_legal_entity_id,
    get_employment_org_unit_id,
    org_unit_ancestor_cte_sql,
)
from hrms.modules.leave.models import (
    LeaveBucketPolicy,
    LeavePolicyAssignment,
    LeavePolicySet,
)
from hrms.modules.org.models import LegalEntity


async def resolve_leave_policy_set(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
    as_of_date: date,
) -> LeavePolicySet | None:
    """
    Resolve the active LeavePolicySet for an employee on a specific date.
    Cascade priority:
    1. Employee-specific assignment
    2. Department-level assignment (walking up org unit parent chain)
    3. Legal-entity assignment (company-wide)
    4. Tenant default policy set
    An assignment whose policy set has been archived falls straight to the tenant
    default (tier 4), not to the next tier.
    """
    assignment = await _employee_assignment(session, tenant_id, employment_id, as_of_date)
    if assignment is None:
        org_unit_id = await get_employment_org_unit_id(
            session, tenant_id, employment_id, as_of_date
        )
        legal_entity_id = await get_employment_legal_entity_id(session, tenant_id, employment_id)
        assignment = await _placement_assignment(
            session, tenant_id, org_unit_id, legal_entity_id, as_of_date
        )
    return await _policy_set_for(session, tenant_id, assignment)


def _active_assignments(tenant_id: UUID, as_of_date: date):
    return (
        select(LeavePolicyAssignment)
        .where(col(LeavePolicyAssignment.tenant_id) == tenant_id)
        .where(col(LeavePolicyAssignment.effective_from) <= as_of_date)
        .where(
            col(LeavePolicyAssignment.effective_to).is_(None)
            | (col(LeavePolicyAssignment.effective_to) >= as_of_date)
        )
        .where(col(LeavePolicyAssignment.archived_at).is_(None))
    )


async def _employee_assignment(
    session: AsyncSession, tenant_id: UUID, employment_id: UUID, as_of_date: date
) -> LeavePolicyAssignment | None:
    """Tier 1: an assignment made to this employee directly."""
    stmt = (
        _active_assignments(tenant_id, as_of_date)
        .where(col(LeavePolicyAssignment.employment_id) == employment_id)
        .order_by(col(LeavePolicyAssignment.effective_from).desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def _placement_assignment(
    session: AsyncSession,
    tenant_id: UUID,
    org_unit_id: UUID | None,
    legal_entity_id: UUID | None,
    as_of_date: date,
) -> LeavePolicyAssignment | None:
    """
    Tiers 2 and 3, which depend only on where the employee sits — their org unit
    (walking up to the root, nearest first) and then their legal entity. Everyone
    with the same placement resolves the same way, which is what lets
    resolve_leave_policy_sets_bulk ask once per placement instead of once per person.
    """
    if org_unit_id is not None:
        cte = org_unit_ancestor_cte_sql()
        match_id = (
            await session.execute(
                text(f"""
                    {cte}
                    SELECT lpa.id
                    FROM leave_policy_assignments lpa
                    JOIN chain ON chain.id = lpa.org_unit_id
                    WHERE lpa.tenant_id = CAST(:tid AS uuid)
                      AND lpa.effective_from <= CAST(:as_of_date AS date)
                      AND (
                          lpa.effective_to IS NULL
                          OR lpa.effective_to >= CAST(:as_of_date AS date)
                      )
                      AND lpa.archived_at IS NULL
                    ORDER BY chain.depth ASC, lpa.effective_from DESC
                    LIMIT 1
                """),
                {"tid": str(tenant_id), "start": str(org_unit_id), "as_of_date": as_of_date},
            )
        ).scalar()
        if match_id is not None:
            found = (
                (
                    await session.execute(
                        select(LeavePolicyAssignment)
                        .where(col(LeavePolicyAssignment.tenant_id) == tenant_id)
                        .where(col(LeavePolicyAssignment.id) == match_id)
                    )
                )
                .scalars()
                .first()
            )
            if found is not None:
                return found
    if legal_entity_id is not None:
        stmt = (
            _active_assignments(tenant_id, as_of_date)
            .where(col(LeavePolicyAssignment.legal_entity_id) == legal_entity_id)
            .order_by(col(LeavePolicyAssignment.effective_from).desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()
    return None


async def _policy_set_for(
    session: AsyncSession, tenant_id: UUID, assignment: LeavePolicyAssignment | None
) -> LeavePolicySet | None:
    """The assignment's (live) policy set, else tier 4: the tenant default."""
    if assignment is not None:
        pset = (
            (
                await session.execute(
                    select(LeavePolicySet)
                    .where(col(LeavePolicySet.tenant_id) == tenant_id)
                    .where(col(LeavePolicySet.id) == assignment.leave_policy_set_id)
                    .where(col(LeavePolicySet.archived_at).is_(None))
                )
            )
            .scalars()
            .first()
        )
        if pset is not None:
            return pset
    default_stmt = (
        select(LeavePolicySet)
        .where(col(LeavePolicySet.tenant_id) == tenant_id)
        .where(col(LeavePolicySet.is_default).is_(True))
        .where(col(LeavePolicySet.archived_at).is_(None))
        .limit(1)
    )
    return (await session.execute(default_stmt)).scalars().first()


async def resolve_leave_policy_sets_bulk(
    session: AsyncSession,
    tenant_id: UUID,
    employment_ids: list[UUID],
    as_of_date: date,
) -> dict[UUID, LeavePolicySet | None]:
    """
    resolve_leave_policy_set for many employees at once, with the same answer for each.
    Tier 1 and every employee's placement come from one query each; tiers 2–4 run once
    per distinct placement (org unit + legal entity) and once per distinct assignment.
    """
    if not employment_ids:
        return {}
    ids = [str(e) for e in employment_ids]
    direct: dict[UUID, LeavePolicyAssignment] = {}
    rows = await session.execute(
        _active_assignments(tenant_id, as_of_date)
        .where(col(LeavePolicyAssignment.employment_id).in_(employment_ids))
        .order_by(
            col(LeavePolicyAssignment.employment_id),
            col(LeavePolicyAssignment.effective_from).desc(),
        )
    )
    for a in rows.scalars():
        assert a.employment_id is not None
        direct.setdefault(UUID(str(a.employment_id)), a)

    placements = await session.execute(
        text("""
            SELECT e.id, e.legal_entity_id, a.org_unit_id
            FROM employments e
            LEFT JOIN LATERAL (
                SELECT org_unit_id FROM assignments
                WHERE tenant_id = e.tenant_id AND employment_id = e.id
                  AND effective_from <= :as_of_date
                  AND (effective_to IS NULL OR effective_to > :as_of_date)
                ORDER BY effective_from DESC LIMIT 1
            ) a ON true
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.id = ANY(CAST(:ids AS uuid[]))
        """),
        {"tid": str(tenant_id), "ids": ids, "as_of_date": as_of_date},
    )
    by_placement: dict[tuple, LeavePolicyAssignment | None] = {}
    by_assignment: dict[UUID | None, LeavePolicySet | None] = {}
    out: dict[UUID, LeavePolicySet | None] = {}
    for raw_emp, raw_le, raw_ou in placements.all():
        # asyncpg returns its own UUID type; normalise so keys match the ORM's uuid.UUID.
        emp_id = UUID(str(raw_emp))
        legal_entity_id = UUID(str(raw_le)) if raw_le else None
        org_unit_id = UUID(str(raw_ou)) if raw_ou else None
        assignment = direct.get(emp_id)
        if assignment is None:
            key = (org_unit_id, legal_entity_id)
            if key not in by_placement:
                by_placement[key] = await _placement_assignment(
                    session, tenant_id, org_unit_id, legal_entity_id, as_of_date
                )
            assignment = by_placement[key]
        akey = assignment.id if assignment is not None else None
        if akey not in by_assignment:
            by_assignment[akey] = await _policy_set_for(session, tenant_id, assignment)
        out[emp_id] = by_assignment[akey]
    return out


async def resolve_bucket_policy(
    session: AsyncSession,
    tenant_id: UUID,
    policy_set_id: UUID,
    bucket_id: UUID,
) -> LeaveBucketPolicy | None:
    """Look up the entitlement policy for a specific bucket within a policy set."""
    stmt = (
        select(LeaveBucketPolicy)
        .where(col(LeaveBucketPolicy.tenant_id) == tenant_id)
        .where(col(LeaveBucketPolicy.policy_set_id) == policy_set_id)
        .where(col(LeaveBucketPolicy.bucket_id) == bucket_id)
    )
    return (await session.execute(stmt)).scalars().first()


async def resolve_employee_bucket_policy(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
    bucket_id: UUID,
    as_of_date: date,
) -> LeaveBucketPolicy | None:
    """Resolve the active bucket policy for an employee by walking the policy set cascade."""
    pset = await resolve_leave_policy_set(session, tenant_id, employment_id, as_of_date)
    if pset is not None:
        bp = await resolve_bucket_policy(session, tenant_id, pset.id, bucket_id)
        if bp is not None:
            return bp

    # Fallback 1: check any default policy set for this bucket (tier 4 tenant default)
    default_bp = (
        await session.execute(
            select(LeaveBucketPolicy)
            .join(LeavePolicySet, col(LeavePolicySet.id) == col(LeaveBucketPolicy.policy_set_id))
            .where(col(LeaveBucketPolicy.tenant_id) == tenant_id)
            .where(col(LeaveBucketPolicy.bucket_id) == bucket_id)
            .where(col(LeavePolicySet.is_default).is_(True))
            .where(col(LeavePolicySet.archived_at).is_(None))
            .order_by(col(LeaveBucketPolicy.recorded_at).desc().nulls_last())
        )
    ).scalars().first()
    if default_bp is not None:
        return default_bp

    # Fallback 2: check any active policy set for this bucket in the tenant
    any_bp = (
        await session.execute(
            select(LeaveBucketPolicy)
            .join(LeavePolicySet, col(LeavePolicySet.id) == col(LeaveBucketPolicy.policy_set_id))
            .where(col(LeaveBucketPolicy.tenant_id) == tenant_id)
            .where(col(LeaveBucketPolicy.bucket_id) == bucket_id)
            .where(col(LeavePolicySet.archived_at).is_(None))
            .order_by(col(LeaveBucketPolicy.recorded_at).desc().nulls_last())
        )
    ).scalars().first()
    if any_bp is not None:
        return any_bp

    # Fallback 3: check any recorded LeaveBucketPolicy for bucket_id
    return (
        await session.execute(
            select(LeaveBucketPolicy)
            .where(col(LeaveBucketPolicy.tenant_id) == tenant_id)
            .where(col(LeaveBucketPolicy.bucket_id) == bucket_id)
            .order_by(col(LeaveBucketPolicy.recorded_at).desc().nulls_last())
        )
    ).scalars().first()


async def resolve_employee_fy_start_month(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
) -> int:
    """
    Determine the financial year start month for an employee.
    Inherits legal_entities.financial_year_start_month if set;
    otherwise falls back to settings.default_financial_year_start_month (default 4).
    """
    legal_entity_id = await get_employment_legal_entity_id(session, tenant_id, employment_id)
    if legal_entity_id is not None:
        le = (
            (
                await session.execute(
                    select(LegalEntity)
                    .where(col(LegalEntity.tenant_id) == tenant_id)
                    .where(col(LegalEntity.id) == legal_entity_id)
                )
            )
            .scalars()
            .first()
        )
        if le and le.financial_year_start_month is not None:
            return le.financial_year_start_month
    return settings.default_financial_year_start_month


async def resolve_fy_start_months_bulk(
    session: AsyncSession, tenant_id: UUID, employment_ids: list[UUID]
) -> dict[UUID, int]:
    """resolve_employee_fy_start_month for many employees in one query."""
    if not employment_ids:
        return {}
    rows = await session.execute(
        text("""
            SELECT e.id, le.financial_year_start_month
            FROM employments e
            LEFT JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
            WHERE e.tenant_id = CAST(:tid AS uuid) AND e.id = ANY(CAST(:ids AS uuid[]))
        """),
        {"tid": str(tenant_id), "ids": [str(e) for e in employment_ids]},
    )
    default = settings.default_financial_year_start_month
    return {UUID(str(e)): (m if m is not None else default) for e, m in rows.all()}

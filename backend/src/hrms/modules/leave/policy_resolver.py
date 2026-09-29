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
    """
    # ── Tier 1: Employee-specific assignment ───────────────────────────────────
    stmt = (
        select(LeavePolicyAssignment)
        .where(col(LeavePolicyAssignment.tenant_id) == tenant_id)
        .where(col(LeavePolicyAssignment.employment_id) == employment_id)
        .where(col(LeavePolicyAssignment.effective_from) <= as_of_date)
        .where(
            col(LeavePolicyAssignment.effective_to).is_(None)
            | (col(LeavePolicyAssignment.effective_to) >= as_of_date)
        )
        .where(col(LeavePolicyAssignment.archived_at).is_(None))
        .order_by(col(LeavePolicyAssignment.effective_from).desc())
        .limit(1)
    )
    assignment: LeavePolicyAssignment | None = (await session.execute(stmt)).scalars().first()

    # ── Tier 2: Department-level assignment ────────────────────────────────────
    if assignment is None:
        org_unit_id = await get_employment_org_unit_id(
            session, tenant_id, employment_id, as_of_date
        )
        if org_unit_id is not None:
            cte = org_unit_ancestor_cte_sql()
            match_row = await session.execute(
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
            match_id = match_row.scalar()
            if match_id is not None:
                assignment = (
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

    # ── Tier 3: Legal-entity assignment (company-wide) ─────────────────────────
    if assignment is None:
        legal_entity_id = await get_employment_legal_entity_id(session, tenant_id, employment_id)
        if legal_entity_id is not None:
            stmt = (
                select(LeavePolicyAssignment)
                .where(col(LeavePolicyAssignment.tenant_id) == tenant_id)
                .where(col(LeavePolicyAssignment.legal_entity_id) == legal_entity_id)
                .where(col(LeavePolicyAssignment.effective_from) <= as_of_date)
                .where(
                    col(LeavePolicyAssignment.effective_to).is_(None)
                    | (col(LeavePolicyAssignment.effective_to) >= as_of_date)
                )
                .where(col(LeavePolicyAssignment.archived_at).is_(None))
                .order_by(col(LeavePolicyAssignment.effective_from).desc())
                .limit(1)
            )
            assignment = (await session.execute(stmt)).scalars().first()

    # Load policy set from resolved assignment
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

    # ── Tier 4: Tenant default policy set ──────────────────────────────────────
    default_stmt = (
        select(LeavePolicySet)
        .where(col(LeavePolicySet.tenant_id) == tenant_id)
        .where(col(LeavePolicySet.is_default).is_(True))
        .where(col(LeavePolicySet.archived_at).is_(None))
        .limit(1)
    )
    return (await session.execute(default_stmt)).scalars().first()


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
    if pset is None:
        return None
    return await resolve_bucket_policy(session, tenant_id, pset.id, bucket_id)


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

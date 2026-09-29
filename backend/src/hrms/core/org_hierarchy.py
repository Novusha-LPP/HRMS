"""
Shared organizational hierarchy utilities.

Provides helper CTE queries and entity/org-unit lookups for policy resolution cascades.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def org_unit_ancestor_cte_sql() -> str:
    """Return the SQL CTE fragment for walking up an org_unit's parent hierarchy."""
    return """
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
    """


async def get_employment_org_unit_id(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
    as_of_date: date,
) -> UUID | None:
    """Find the employee's active org_unit_id from assignments."""
    result = await session.execute(
        text("""
            SELECT org_unit_id FROM assignments
            WHERE tenant_id = CAST(:tid AS uuid) AND employment_id = CAST(:eid AS uuid)
              AND effective_from <= :as_of_date
              AND (effective_to IS NULL OR effective_to > :as_of_date)
            ORDER BY effective_from DESC LIMIT 1
        """),
        {"tid": str(tenant_id), "eid": str(employment_id), "as_of_date": as_of_date},
    )
    val = result.scalar()
    return UUID(str(val)) if val else None


async def get_employment_legal_entity_id(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
) -> UUID | None:
    """Find the employee's legal_entity_id from their employment record."""
    result = await session.execute(
        text("""
            SELECT legal_entity_id FROM employments
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:eid AS uuid)
        """),
        {"tid": str(tenant_id), "eid": str(employment_id)},
    )
    val = result.scalar()
    return UUID(str(val)) if val else None

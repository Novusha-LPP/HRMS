"""
Authorization — turns a signed-in user's role_assignments into a Scope that
every list/aggregate query and every row-level check must apply.

Nothing here trusts client-supplied identity. The caller's own employment id
and roles always come from core.authn.Principal (a verified JWT); the only
input from the client is which *resource* it's asking for, which this module
checks against the resolved Scope.

Scope composition, from role_assignments.scope_type:
  ALL            — every legal entity in the tenant (group HR, super admin)
  LEGAL_ENTITY   — a specific set of companies (e.g. a shared accountant)
  ORG_UNIT       — a department and everything under it, resolved to the
                   legal entities those org units belong to
  SELF           — only the caller's own employment record
  DIRECT_REPORTS — the caller's own record plus their direct reports
  ALL_REPORTS    — the caller's own record plus their full reporting chain

A user can hold several role_assignments; the effective scope is their union.
Holding no assignment at all fails closed to SELF (or nothing, if the account
has no employment).
"""

import json
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.authn import CurrentUser, Principal
from hrms.core.database import SessionDep
from hrms.core.ids import to_uuid
from hrms.core.tenancy import TenantDep

# Permission bundles per role name. There's no separate permissions table —
# roles ARE the permission bundles, keyed by name so seed data / an admin UI
# can grant them without touching code. "*" grants everything.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "SUPER_ADMIN": frozenset({"*"}),
    "HR_MANAGER": frozenset({
        "people.read", "people.write",
        "org.read", "org.write",
        "iam.read", "iam.write",
        "leave.read", "leave.approve", "leave.write",
        "corrections.read", "corrections.approve",
        "onboarding.read", "onboarding.write",
        "policy.read", "policy.write",
        "reports.read", "reports.write",
        "dashboard.hr",
    }),
    "MANAGER": frozenset({
        "people.read",
        "leave.approve", "corrections.approve",
        "onboarding.read",
        "reports.read",
        "dashboard.manager",
    }),
    "EMPLOYEE": frozenset({"self.read", "self.write", "leave.apply", "corrections.request", "reports.read"}),
    "ACCOUNTANT": frozenset({"people.read", "reports.read", "dashboard.hr"}),
}

# Human-readable blurb for each system role — the single source of truth for
# both the seed script and tenant registration, which both bootstrap the same
# five roles for a brand-new tenant.
ROLE_DESCRIPTIONS: dict[str, str] = {
    "SUPER_ADMIN": "Full platform access across every company",
    "HR_MANAGER": "Manage people, approvals and policy for companies in scope",
    "MANAGER": "Approve leave/corrections and view direct reports",
    "EMPLOYEE": "Self-service only",
    "ACCOUNTANT": "Read-only people + reports access for companies in scope",
}


@dataclass(frozen=True)
class Scope:
    is_all: bool
    legal_entity_ids: frozenset[UUID]
    # None = "not restricted to a specific employment set" (is_all or
    # legal_entity_ids governs instead). An empty frozenset = no access at all.
    employment_ids: frozenset[UUID] | None
    permissions: frozenset[str]
    own_employment_id: UUID | None
    role_names: frozenset[str]

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )

    def covers_entity(self, legal_entity_id: UUID | None) -> bool:
        if self.is_all:
            return True
        return legal_entity_id is not None and legal_entity_id in self.legal_entity_ids

    def employment_filter_sql(self, alias: str = "e") -> tuple[str, dict[str, object]]:
        """
        SQL fragment (empty, or starting with 'AND') plus its bind params,
        for queries that select FROM employments <alias> or join it in.
        """
        if self.is_all:
            return "", {}
        if self.employment_ids is not None:
            if not self.employment_ids:
                return "AND FALSE", {}
            return (
                f"AND {alias}.id = ANY(CAST(:scope_employment_ids AS uuid[]))",
                {"scope_employment_ids": [str(i) for i in self.employment_ids]},
            )
        if self.legal_entity_ids:
            return (
                f"AND {alias}.legal_entity_id = ANY(CAST(:scope_entity_ids AS uuid[]))",
                {"scope_entity_ids": [str(i) for i in self.legal_entity_ids]},
            )
        return "AND FALSE", {}


def _decode_scope_ids(raw: str | None) -> set[UUID]:
    """scope_value is a JSON array of typed ids, e.g. '["le_...", "le_..."]'."""
    if not raw:
        return set()
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        return set()
    out: set[UUID] = set()
    for v in values:
        if not isinstance(v, str):
            continue
        try:
            out.add(to_uuid(v) if "_" in v else UUID(v))
        except (ValueError, IndexError):
            continue
    return out


# Public alias — other modules (e.g. kernel/users) need to decode
# role_assignments.scope_value the same way resolve_scope does.
decode_scope_ids = _decode_scope_ids


async def _entities_for_org_units(
    session: AsyncSession, tenant_id: UUID, org_unit_ids: set[UUID]
) -> set[UUID]:
    if not org_unit_ids:
        return set()
    rows = await session.execute(
        text("""
            WITH RECURSIVE descendants AS (
                SELECT id, legal_entity_id
                FROM org_units
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND id = ANY(CAST(:ids AS uuid[]))
                UNION ALL
                SELECT ou.id, ou.legal_entity_id
                FROM org_units ou
                JOIN descendants d ON ou.parent_id = d.id
                WHERE ou.tenant_id = CAST(:tid AS uuid)
            )
            SELECT DISTINCT legal_entity_id FROM descendants WHERE legal_entity_id IS NOT NULL
        """),
        {"tid": str(tenant_id), "ids": [str(i) for i in org_unit_ids]},
    )
    return {r[0] for r in rows}


async def _direct_reports(session: AsyncSession, tenant_id: UUID, manager_employment_id: UUID) -> set[UUID]:
    rows = await session.execute(
        text("""
            SELECT DISTINCT a.employment_id
            FROM assignment_managers am
            JOIN assignments a ON a.tenant_id = am.tenant_id AND a.id = am.assignment_id
            WHERE am.tenant_id = CAST(:tid AS uuid)
              AND am.manager_employment_id = CAST(:mgr AS uuid)
              AND am.effective_to IS NULL
        """),
        {"tid": str(tenant_id), "mgr": str(manager_employment_id)},
    )
    return {r[0] for r in rows}


async def _all_reports(session: AsyncSession, tenant_id: UUID, manager_employment_id: UUID) -> set[UUID]:
    """Direct reports, their reports, and so on (depth-capped against cycles)."""
    rows = await session.execute(
        text("""
            WITH RECURSIVE chain AS (
                SELECT a.employment_id AS employment_id, 1 AS depth
                FROM assignment_managers am
                JOIN assignments a ON a.tenant_id = am.tenant_id AND a.id = am.assignment_id
                WHERE am.tenant_id = CAST(:tid AS uuid)
                  AND am.manager_employment_id = CAST(:mgr AS uuid)
                  AND am.effective_to IS NULL
                UNION ALL
                SELECT a2.employment_id, chain.depth + 1
                FROM chain
                JOIN assignment_managers am2
                    ON am2.tenant_id = CAST(:tid AS uuid)
                   AND am2.manager_employment_id = chain.employment_id
                   AND am2.effective_to IS NULL
                JOIN assignments a2
                    ON a2.tenant_id = CAST(:tid AS uuid) AND a2.id = am2.assignment_id
                WHERE chain.depth < 12
            )
            SELECT DISTINCT employment_id FROM chain
        """),
        {"tid": str(tenant_id), "mgr": str(manager_employment_id)},
    )
    return {r[0] for r in rows}


async def resolve_scope(session: AsyncSession, tenant_id: UUID, principal: Principal) -> Scope:
    rows = await session.execute(
        text("""
            SELECT r.name AS role_name, ra.scope_type, ra.scope_value
            FROM role_assignments ra
            JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
            WHERE ra.tenant_id = CAST(:tid AS uuid)
              AND ra.user_account_id = CAST(:uid AS uuid)
              AND (ra.expires_at IS NULL OR ra.expires_at > now())
        """),
        {"tid": str(tenant_id), "uid": str(principal.user_account_id)},
    )
    grants = rows.mappings().all()

    is_all = False
    legal_entity_ids: set[UUID] = set()
    employment_ids: set[UUID] | None = None
    permissions: set[str] = set()
    role_names: set[str] = set()
    has_broad_grant = False  # ALL / LEGAL_ENTITY / ORG_UNIT lifts any narrow employment_ids cap

    for g in grants:
        role_names.add(g["role_name"])
        permissions |= ROLE_PERMISSIONS.get(g["role_name"], frozenset())

        scope_type = g["scope_type"]
        if scope_type == "ALL":
            is_all = True
            has_broad_grant = True
        elif scope_type == "LEGAL_ENTITY":
            legal_entity_ids |= _decode_scope_ids(g["scope_value"])
            has_broad_grant = True
        elif scope_type == "ORG_UNIT":
            org_unit_ids = _decode_scope_ids(g["scope_value"])
            legal_entity_ids |= await _entities_for_org_units(session, tenant_id, org_unit_ids)
            has_broad_grant = True
        elif scope_type == "SELF" and principal.employment_id:
            employment_ids = (employment_ids or set()) | {principal.employment_id}
        elif scope_type == "DIRECT_REPORTS" and principal.employment_id:
            reports = await _direct_reports(session, tenant_id, principal.employment_id)
            employment_ids = (employment_ids or set()) | reports | {principal.employment_id}
        elif scope_type == "ALL_REPORTS" and principal.employment_id:
            reports = await _all_reports(session, tenant_id, principal.employment_id)
            employment_ids = (employment_ids or set()) | reports | {principal.employment_id}

    if has_broad_grant:
        employment_ids = None  # a company/department grant supersedes a narrower one

    if not grants:
        # No role at all: fail closed to "only my own record" rather than "all".
        employment_ids = {principal.employment_id} if principal.employment_id else set()

    return Scope(
        is_all=is_all,
        legal_entity_ids=frozenset(legal_entity_ids),
        employment_ids=frozenset(employment_ids) if employment_ids is not None else None,
        permissions=frozenset(permissions),
        own_employment_id=principal.employment_id,
        role_names=frozenset(role_names),
    )


async def get_current_scope(principal: CurrentUser, tenant_id: TenantDep, session: SessionDep) -> Scope:
    # tenant_id is declared here (not just read off principal) so that
    # tenant_from_request — which sets the RLS/session tenant context —
    # is guaranteed to run before this function's own `session` dependency
    # opens a connection, no matter where ScopeDep sits relative to a
    # sibling TenantDep/SessionDep parameter in the route that uses it.
    return await resolve_scope(session, tenant_id, principal)


ScopeDep = Annotated[Scope, Depends(get_current_scope)]


def require_permission(permission: str):
    async def _dep(scope: ScopeDep) -> Scope:
        scope.require(permission)
        return scope

    return Depends(_dep)


async def employment_legal_entity(session: AsyncSession, tenant_id: UUID, employment_id: UUID) -> UUID | None:
    row = await session.execute(
        text("""
            SELECT legal_entity_id FROM employments
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:eid AS uuid)
        """),
        {"tid": str(tenant_id), "eid": str(employment_id)},
    )
    return row.scalar()


async def authorize_employment(
    session: AsyncSession, tenant_id: UUID, scope: Scope, target_employment_id: UUID
) -> None:
    """Raise 403/404 unless the caller's scope covers this specific employee."""
    if scope.is_all:
        return
    if scope.employment_ids is not None and target_employment_id in scope.employment_ids:
        return
    if scope.legal_entity_ids:
        entity_id = await employment_legal_entity(session, tenant_id, target_employment_id)
        if entity_id is not None and entity_id in scope.legal_entity_ids:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this employee")


def resolve_acting_employment_id(principal: Principal, requested: str | None) -> UUID:
    """
    For self-service actions (apply leave, punch, request a correction): the
    acting employment is always the caller's own unless they explicitly pass
    a different one, which is then checked against scope by the caller via
    authorize_employment. Never silently trusts a bare query param as-is.
    """
    if requested:
        return to_uuid(requested)
    if principal.employment_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account has no employment record")
    return principal.employment_id

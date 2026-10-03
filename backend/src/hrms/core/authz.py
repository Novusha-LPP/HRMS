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
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import Uuid, text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.authn import CurrentUser, Principal
from hrms.core.database import GRANTS_KEY, SessionDep
from hrms.core.ids import to_uuid
from hrms.core.tenancy import TenantDep

# Permission bundles per role name. There's no separate permissions table —
# roles ARE the permission bundles, keyed by name so seed data / an admin UI
# can grant them without touching code. "*" grants everything.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "SUPER_ADMIN": frozenset({"*"}),
    "HR_MANAGER": frozenset(
        {
            "self.read",
            "self.write",
            "leave.apply",
            "corrections.request",
            "people.read",
            "people.write",
            "org.read",
            "org.write",
            "iam.read",
            "iam.write",
            "leave.read",
            "leave.approve",
            "leave.write",
            "corrections.read",
            "corrections.approve",
            "corrections.write",
            "time.write",
            "onboarding.read",
            "onboarding.write",
            "policy.read",
            "policy.write",
            "reports.read",
            "reports.write",
            "dashboard.hr",
            "kyc.self",
            "kyc.read",
            "kyc.write",
            "kyc.verify",
        }
    ),
    "MANAGER": frozenset(
        {
            "self.read",
            "self.write",
            "leave.apply",
            "corrections.request",
            "people.read",
            "leave.approve",
            "corrections.approve",
            "onboarding.read",
            "reports.read",
            "dashboard.manager",
            "kyc.read",
        }
    ),
    "EMPLOYEE": frozenset(
        {
            "self.read",
            "self.write",
            "leave.apply",
            "corrections.request",
            "reports.read",
            "kyc.self",
        }
    ),
    "ACCOUNTANT": frozenset({"people.read", "reports.read", "dashboard.hr", "kyc.read"}),
}

# Roles that only ever act on the caller's own record, whatever scope their
# role assignment claims — see resolve_scope and users/router.create_user.
SELF_SERVICE_ONLY_ROLES = frozenset({"EMPLOYEE"})

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
    org_unit_ids: frozenset[UUID] = frozenset()
    grants: tuple["Scope", ...] = field(default=(), repr=False)

    def for_permission(self, permission: str) -> "Scope":
        """Keep the scope attached to each grant of this permission."""
        self.require(permission)
        if not self.grants:
            return self
        return merge_scopes([g for g in self.grants if g.has(permission)], self.own_employment_id)

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
        clauses = []
        params: dict[str, object] = {}
        if self.employment_ids:
            clauses.append(f"{alias}.id = ANY(CAST(:scope_employment_ids AS uuid[]))")
            params["scope_employment_ids"] = [str(i) for i in self.employment_ids]
        if self.legal_entity_ids:
            clauses.append(f"{alias}.legal_entity_id = ANY(CAST(:scope_entity_ids AS uuid[]))")
            params["scope_entity_ids"] = [str(i) for i in self.legal_entity_ids]
        return ("AND (" + " OR ".join(clauses) + ")", params) if clauses else ("AND FALSE", {})


def merge_scopes(grants: list[Scope], own: UUID | None) -> Scope:
    grants = [leaf for grant in grants for leaf in (grant.grants or (grant,))]

    def union(name):
        return frozenset().union(*(getattr(g, name) or frozenset() for g in grants))

    return Scope(
        is_all=any(g.is_all for g in grants),
        legal_entity_ids=union("legal_entity_ids"),
        employment_ids=union("employment_ids")
        if union("employment_ids") or not union("legal_entity_ids")
        else None,
        permissions=union("permissions"),
        own_employment_id=own,
        role_names=union("role_names"),
        org_unit_ids=union("org_unit_ids"),
        grants=tuple(grants),
    )


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
        except (ValueError, IndexError, HTTPException):
            continue
    return out


# Public alias — other modules (e.g. kernel/users) need to decode
# role_assignments.scope_value the same way resolve_scope does.
decode_scope_ids = _decode_scope_ids


async def _department_scope(session, tenant_id: UUID, org_unit_ids: set[UUID]):
    if not org_unit_ids:
        return frozenset(), frozenset()
    rows = await session.execute(
        text("""
        WITH RECURSIVE descendants AS (
            SELECT id FROM org_units WHERE tenant_id = :tid AND id = ANY(CAST(:ids AS uuid[]))
            UNION
            SELECT ou.id FROM org_units ou JOIN descendants d ON ou.parent_id = d.id
            WHERE ou.tenant_id = :tid
        )
        SELECT d.id, a.employment_id FROM descendants d
        LEFT JOIN assignments a ON a.tenant_id = :tid AND a.org_unit_id = d.id
            AND a.effective_from <= CURRENT_DATE
            AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
    """),
        {"tid": tenant_id, "ids": [str(i) for i in org_unit_ids]},
    )
    rows = list(rows)
    return frozenset(r[0] for r in rows), frozenset(r[1] for r in rows if r[1])


async def _direct_reports(
    session: AsyncSession, tenant_id: UUID, manager_employment_id: UUID
) -> set[UUID]:
    rows = await session.execute(
        text("""
            SELECT DISTINCT a.employment_id
            FROM assignment_managers am
            JOIN assignments a ON a.tenant_id = am.tenant_id AND a.id = am.assignment_id
            WHERE am.tenant_id = CAST(:tid AS uuid)
              AND am.manager_employment_id = CAST(:mgr AS uuid)
              AND am.effective_from <= CURRENT_DATE
              AND (am.effective_to IS NULL OR am.effective_to > CURRENT_DATE)
              AND a.effective_from <= CURRENT_DATE
              AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
        """),
        {"tid": str(tenant_id), "mgr": str(manager_employment_id)},
    )
    return {r[0] for r in rows}


async def _all_reports(
    session: AsyncSession, tenant_id: UUID, manager_employment_id: UUID
) -> set[UUID]:
    """Direct reports, their reports, and so on (depth-capped against cycles)."""
    rows = await session.execute(
        text("""
            WITH RECURSIVE chain AS (
                SELECT a.employment_id AS employment_id, 1 AS depth
                FROM assignment_managers am
                JOIN assignments a ON a.tenant_id = am.tenant_id AND a.id = am.assignment_id
                WHERE am.tenant_id = CAST(:tid AS uuid)
                  AND am.manager_employment_id = CAST(:mgr AS uuid)
                  AND am.effective_from <= CURRENT_DATE
              AND (am.effective_to IS NULL OR am.effective_to > CURRENT_DATE)
              AND a.effective_from <= CURRENT_DATE
              AND (a.effective_to IS NULL OR a.effective_to > CURRENT_DATE)
                UNION ALL
                SELECT a2.employment_id, chain.depth + 1
                FROM chain
                JOIN assignment_managers am2
                    ON am2.tenant_id = CAST(:tid AS uuid)
                   AND am2.manager_employment_id = chain.employment_id
                   AND am2.effective_from <= CURRENT_DATE
                   AND (am2.effective_to IS NULL OR am2.effective_to > CURRENT_DATE)
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
    # get_session already read this user's live grants in its account-check round trip;
    # anything else (scripts, other sessions) reads them here.
    fetched = getattr(session, "info", {}).get(GRANTS_KEY)
    if fetched is not None and fetched[0] == principal.user_account_id:
        grants = fetched[1]
    else:
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

    resolved = []
    for g in grants:
        kind = g["scope_type"]
        if g["role_name"] in SELF_SERVICE_ONLY_ROLES:
            # "Self-service only" is what the role means. Read endpoints filter by
            # the caller's scope, so an EMPLOYEE assignment stored with a company
            # scope (an import that assigned every account the same scope did
            # exactly that) would expose the whole company's records. Whatever is
            # stored, this role never resolves to more than the caller's own record.
            kind = "SELF"
        entities: frozenset[UUID] = frozenset()
        employees: frozenset[UUID] = frozenset()
        departments: frozenset[UUID] = frozenset()
        if kind == "LEGAL_ENTITY":
            entities = frozenset(_decode_scope_ids(g["scope_value"]))
        elif kind == "ORG_UNIT":
            departments, employees = await _department_scope(
                session, tenant_id, _decode_scope_ids(g["scope_value"])
            )
        elif principal.employment_id and kind in ("SELF", "DIRECT_REPORTS", "ALL_REPORTS"):
            employees = frozenset({principal.employment_id})
            if kind == "DIRECT_REPORTS":
                employees |= await _direct_reports(session, tenant_id, principal.employment_id)
            elif kind == "ALL_REPORTS":
                employees |= await _all_reports(session, tenant_id, principal.employment_id)
        resolved.append(
            Scope(
                is_all=kind == "ALL",
                legal_entity_ids=entities,
                employment_ids=employees,
                permissions=ROLE_PERMISSIONS.get(g["role_name"], frozenset()),
                own_employment_id=principal.employment_id,
                role_names=frozenset({g["role_name"]}),
                org_unit_ids=departments,
            )
        )
    return merge_scopes(resolved, principal.employment_id)


async def get_current_scope(
    principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> Scope:
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


async def employment_legal_entity(
    session: AsyncSession, tenant_id: UUID, employment_id: UUID
) -> UUID | None:
    row = await session.execute(
        text("""
            SELECT legal_entity_id FROM employments
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:eid AS uuid)
        """),
        {"tid": str(tenant_id), "eid": str(employment_id)},
    )
    return row.scalar()


async def org_unit_legal_entity(
    session: AsyncSession, tenant_id: UUID, org_unit_id: UUID
) -> UUID | None:
    row = await session.execute(
        text("""
            SELECT legal_entity_id FROM org_units
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:oid AS uuid)
        """),
        {"tid": str(tenant_id), "oid": str(org_unit_id)},
    )
    return row.scalar()


async def authorize_org_unit(
    session: AsyncSession, tenant_id: UUID, scope: Scope, org_unit_id: UUID
) -> None:
    """Raise 403/404 unless the caller's scope covers this org unit's legal entity."""
    if scope.is_all or org_unit_id in scope.org_unit_ids:
        return
    entity_id = await org_unit_legal_entity(session, tenant_id, org_unit_id)
    if entity_id is not None and scope.covers_entity(entity_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this department"
    )


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
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this employee"
    )


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


async def authorize_write(
    session,
    tenant_id: UUID,
    scope: Scope,
    principal: Principal,
    target: UUID,
    permission: str,
    self_permission: str = "self.write",
) -> None:
    if target == principal.employment_id:
        # Staff with an employment can use self-service, too. Read-only roles cannot.
        if not (scope.has(self_permission) or scope.has(permission)):
            raise HTTPException(403, "Missing self-service permission")
        return
    await authorize_employment(session, tenant_id, scope.for_permission(permission), target)


def visible_employments_select(tenant_id: UUID, scope: Scope):
    """
    The same set as visible_employment_ids, as a subquery to embed with
    `col(X.employment_id).in_(...)` — Postgres filters in one statement instead of the
    ids making a round trip into Python and back as an IN list of thousands.
    """
    clause, params = scope.employment_filter_sql("e")
    return (
        text(f"SELECT e.id FROM employments e WHERE e.tenant_id = :visible_tid {clause}")
        .bindparams(visible_tid=tenant_id, **params)
        .columns(id=Uuid)
    )


async def visible_employment_ids(session, tenant_id: UUID, scope: Scope) -> list[UUID]:
    clause, params = scope.employment_filter_sql("e")
    rows = await session.execute(
        text(f"SELECT e.id FROM employments e WHERE e.tenant_id = :tid {clause}"),
        {"tid": tenant_id, **params},
    )
    return [r[0] for r in rows]


def require_global_permission(permission: str):
    async def dependency(scope: ScopeDep):
        if not scope.for_permission(permission).is_all:
            raise HTTPException(403, "Tenant-wide configuration requires all-company access")

    return Depends(dependency)


def read_scope(scope: Scope, *permissions: str) -> Scope:
    grants = [scope.for_permission(p) for p in permissions if scope.has(p)]
    if scope.own_employment_id and scope.has("self.read"):
        grants.append(
            Scope(
                False,
                frozenset(),
                frozenset({scope.own_employment_id}),
                frozenset({"self.read"}),
                scope.own_employment_id,
                frozenset(),
            )
        )
    return merge_scopes(grants, scope.own_employment_id)


# Recorded as the actor (recorded_by, approved_by, …) on changes the platform makes by itself,
# such as the scheduled leave accrual — the audit columns stay NOT NULL and every row says who.
SYSTEM_ACTOR = UUID(int=0)

"""
Who may do what in recruitment.

Raising an opening is open to whoever leads part of the organisation — the head of a
department, a team's lead or its PM (org_units.head/lead/pm_employment_id) — as well
as roles holding `recruitment.request`. Those people see the openings they raised,
manage or lead, and the candidates in them (read-only, plus feedback).

HR (`recruitment.read` / `recruitment.manage`) works every opening in the companies
their role covers; `recruitment.approve` signs off openings that no configured
approval flow routes. The pipeline itself is tenant-wide configuration.
"""

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from hrms.core.authn import Principal
from hrms.core.authz import Scope
from hrms.core.datetime_utils import business_today
from hrms.core.org_hierarchy import get_employment_org_unit_id
from hrms.modules.recruitment.models import JobOpening


def _grant(scope: Scope, permission: str) -> Scope | None:
    return scope.for_permission(permission) if scope.has(permission) else None


@dataclass(frozen=True)
class Access:
    user_id: UUID
    employment_id: UUID | None
    read: Scope | None
    manage: Scope | None
    approve: Scope | None
    request_role: bool
    led_units: frozenset[UUID]
    own_unit: UUID | None

    # ── broad capabilities ──────────────────────────────────────────────
    @property
    def can_manage_any(self) -> bool:
        return self.manage is not None

    @property
    def can_request(self) -> bool:
        return (
            self.can_manage_any
            or bool(self.led_units)
            or (self.request_role and self.own_unit is not None)
        )

    @property
    def manages_pipeline(self) -> bool:
        """Pipeline stages are shared by every company in the tenant."""
        return self.manage is not None and self.manage.is_all

    # ── per opening ─────────────────────────────────────────────────────
    @staticmethod
    def _covers(scope: Scope | None, legal_entity_id: UUID, org_unit_id: UUID) -> bool:
        if scope is None:
            return False
        return scope.covers_entity(legal_entity_id) or org_unit_id in scope.org_unit_ids

    def manages(self, opening: JobOpening) -> bool:
        return self._covers(self.manage, opening.legal_entity_id, opening.org_unit_id)

    def approves(self, opening: JobOpening) -> bool:
        return self._covers(self.approve, opening.legal_entity_id, opening.org_unit_id)

    def recruiter_view(self, opening: JobOpening) -> bool:
        return self.manages(opening) or self._covers(
            self.read, opening.legal_entity_id, opening.org_unit_id
        )

    def stakeholder(self, opening: JobOpening) -> bool:
        return (
            opening.requested_by == self.user_id
            or (
                self.employment_id is not None
                and opening.hiring_manager_employment_id == self.employment_id
            )
            or opening.org_unit_id in self.led_units
        )

    def can_view(self, opening: JobOpening) -> bool:
        return self.recruiter_view(opening) or self.stakeholder(opening)

    def require_view(self, opening: JobOpening) -> None:
        if not self.can_view(opening):
            # Indistinguishable from a missing opening on purpose.
            raise HTTPException(404, "Opening not found")

    def require_manage(self, opening: JobOpening) -> None:
        self.require_view(opening)
        if not self.manages(opening):
            raise HTTPException(403, "Only recruiters for this company can do that")

    def may_raise_for(self, org_unit_id: UUID, legal_entity_id: UUID | None) -> bool:
        if legal_entity_id is not None and self._covers(self.manage, legal_entity_id, org_unit_id):
            return True
        if org_unit_id in self.led_units:
            return True
        return self.request_role and self.own_unit == org_unit_id

    # ── SQL for lists ───────────────────────────────────────────────────
    def opening_filter_sql(self, alias: str = "o") -> tuple[str, dict]:
        """`AND (...)` restricting job_openings <alias> to what this caller may see."""
        clauses = [f"{alias}.requested_by = :acc_uid", f"{alias}.org_unit_id = ANY(:acc_led)"]
        params: dict = {"acc_uid": self.user_id, "acc_led": list(self.led_units)}
        if self.employment_id is not None:
            clauses.append(f"{alias}.hiring_manager_employment_id = :acc_eid")
            params["acc_eid"] = self.employment_id
        entities: set[UUID] = set()
        units: set[UUID] = set()
        for scope in (self.read, self.manage):
            if scope is None:
                continue
            if scope.is_all:
                return "", {}
            entities |= scope.legal_entity_ids
            units |= scope.org_unit_ids
        if entities:
            clauses.append(f"{alias}.legal_entity_id = ANY(:acc_entities)")
            params["acc_entities"] = list(entities)
        if units:
            clauses.append(f"{alias}.org_unit_id = ANY(:acc_units)")
            params["acc_units"] = list(units)
        return "AND (" + " OR ".join(clauses) + ")", params

    def recruiter_filter_sql(self, alias: str = "o") -> tuple[str, dict] | None:
        """Openings this caller recruits for (None = none at all)."""
        entities: set[UUID] = set()
        units: set[UUID] = set()
        found = False
        for scope in (self.read, self.manage):
            if scope is None:
                continue
            found = True
            if scope.is_all:
                return "", {}
            entities |= scope.legal_entity_ids
            units |= scope.org_unit_ids
        if not found:
            return None
        clauses = []
        params: dict = {}
        if entities:
            clauses.append(f"{alias}.legal_entity_id = ANY(:rec_entities)")
            params["rec_entities"] = list(entities)
        if units:
            clauses.append(f"{alias}.org_unit_id = ANY(:rec_units)")
            params["rec_units"] = list(units)
        return ("AND (" + " OR ".join(clauses) + ")", params) if clauses else ("AND FALSE", {})


async def led_unit_ids(session, tenant_id: UUID, employment_id: UUID | None) -> frozenset[UUID]:
    """Active units this person heads, leads or PMs, and everything beneath them."""
    if employment_id is None:
        return frozenset()
    rows = await session.execute(
        text("""
            WITH RECURSIVE led AS (
                SELECT id FROM org_units
                WHERE tenant_id = :tid AND status = 'ACTIVE' AND archived_at IS NULL
                  AND :eid IN (head_employment_id, lead_employment_id, pm_employment_id)
                UNION
                SELECT ou.id FROM org_units ou JOIN led ON ou.parent_id = led.id
                WHERE ou.tenant_id = :tid AND ou.status = 'ACTIVE' AND ou.archived_at IS NULL
            )
            SELECT id FROM led
        """),
        {"tid": tenant_id, "eid": employment_id},
    )
    return frozenset(r[0] for r in rows)


async def load_access(session, tenant_id: UUID, principal: Principal, scope: Scope) -> Access:
    employment_id = principal.employment_id
    request_role = scope.has("recruitment.request")
    own_unit = None
    if request_role and employment_id is not None:
        own_unit = await get_employment_org_unit_id(
            session, tenant_id, employment_id, business_today()
        )
    return Access(
        user_id=principal.user_account_id,
        employment_id=employment_id,
        read=_grant(scope, "recruitment.read"),
        manage=_grant(scope, "recruitment.manage"),
        approve=_grant(scope, "recruitment.approve"),
        request_role=request_role,
        led_units=await led_unit_ids(session, tenant_id, employment_id),
        own_unit=own_unit,
    )

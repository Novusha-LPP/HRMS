"""
Field ownership and lifecycle rules, enforced on HRMS's own write paths (plan §6.2).

assert_fields_editable() is the one place that decides whether HR (or the employee) may change
a field on an employee linked to a two-way app. Every HRMS write path for a catalogue field
calls it; tests/test_integrations_ownership.py fails if a path stops doing so.

The common case, an employee no app is linked to, costs one indexed query.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.change_audit import record_change
from hrms.core.errors import CodedHTTPException
from hrms.modules.integrations.catalog import FIELDS, OWNABLE_FIELDS, IntegrationSettings
from hrms.modules.integrations.profiles import effective_settings

# Personnel-action change keys -> catalogue fields.
ASSIGNMENT_FIELDS = {
    "org_unit_id": "department",
    "location_id": "location",
    "job_id": "designation",
    "manager_employment_id": "manager",
}


@dataclass(frozen=True)
class LinkedApp:
    app_id: UUID
    code: str
    name: str
    external_id: str
    settings: IntegrationSettings


async def linked_apps(
    session: AsyncSession, tenant_id: UUID, employment_id: UUID
) -> list[LinkedApp]:
    """The two-way apps this employee is linked to, with the settings for their company."""
    rows = (
        (
            await session.execute(
                text("""
                SELECT ca.id, ca.code, ca.name, x.external_id, e.legal_entity_id
                FROM external_identities x
                JOIN connected_apps ca ON ca.tenant_id = x.tenant_id AND ca.id = x.app_id
                JOIN employments e ON e.tenant_id = x.tenant_id AND e.id = x.employment_id
                WHERE x.tenant_id = :tid AND x.employment_id = :eid
                  AND ca.kind = 'TWO_WAY' AND ca.status <> 'DISCONNECTED'
                ORDER BY ca.code
            """),
                {"tid": tenant_id, "eid": employment_id},
            )
        )
        .mappings()
        .all()
    )
    return [
        LinkedApp(
            app_id=r["id"],
            code=r["code"],
            name=r["name"],
            external_id=r["external_id"],
            settings=await effective_settings(session, tenant_id, r["id"], r["legal_entity_id"]),
        )
        for r in rows
    ]


async def assert_fields_editable(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
    fields: set[str] | list[str],
    *,
    actor: Literal["HR", "SELF"],
    changed_by: UUID,
    override_reason: str | None = None,
) -> list[str]:
    """
    Refuse a change in HRMS to a field an app owns, unless the app's settings allow HR to
    override it and a reason is given. The employee can never override (actor SELF).

    Returns the names of the apps whose settings require the override to be approved first
    (hr_override WITH_APPROVAL); the caller holds the change until the approval completes.
    """
    wanted = {f for f in fields if f in FIELDS}
    needs_approval: list[str] = []
    if not wanted:
        return needs_approval
    for app in await linked_apps(session, tenant_id, employment_id):
        owned = sorted(f for f in wanted if app.settings.owner(f) == "APP")
        if not owned:
            continue
        labels = ", ".join(FIELDS[f]["label"].lower() for f in owned)
        verb = "is" if len(owned) == 1 else "are"
        if actor == "SELF":
            raise CodedHTTPException(
                403,
                f"Your {labels} {verb} managed in {app.name}. Ask HR to change it there.",
                code="FIELD_MANAGED_EXTERNALLY",
            )
        if app.settings.hr_override == "NOT_ALLOWED":
            raise CodedHTTPException(
                403,
                f"{labels.capitalize()} {verb} managed in {app.name} for this employee. "
                "Change it there.",
                code="FIELD_MANAGED_EXTERNALLY",
            )
        if not (override_reason and override_reason.strip()):
            raise CodedHTTPException(
                403,
                f"{labels.capitalize()} {verb} managed in {app.name}. To change it here, give a "
                "reason for the override.",
                code="OVERRIDE_REASON_REQUIRED",
            )
        await record_change(
            session,
            tenant_id,
            "integration_override",
            employment_id,
            "UPDATE",
            changed_by,
            None,
            {
                "app": app.code,
                "fields": ",".join(owned),
                "reason": override_reason.strip(),
                "approval": app.settings.hr_override == "WITH_APPROVAL",
            },
        )
        if app.settings.hr_override == "WITH_APPROVAL":
            needs_approval.append(app.name)
        session.info.setdefault("integration_overrides", {}).setdefault(app.app_id, set()).update(
            owned
        )
    return needs_approval


async def assert_lifecycle_allowed(
    session: AsyncSession,
    tenant_id: UUID,
    operation: Literal["hire", "job_change", "exit", "rehire"],
    *,
    legal_entity_id: UUID | None = None,
    employment_id: UUID | None = None,
) -> None:
    """
    Refuse a lifecycle operation in HRMS that a two-way app's settings reserve for the app:
    hiring into a company (any active two-way app counts), or a change to a linked employee.
    """
    if employment_id is not None:
        apps = await linked_apps(session, tenant_id, employment_id)
        candidates = [(a.name, a.settings) for a in apps]
    else:
        rows = (
            (
                await session.execute(
                    text("""
                    SELECT id, name FROM connected_apps
                    WHERE tenant_id = :tid AND kind = 'TWO_WAY' AND status = 'ACTIVE'
                """),
                    {"tid": tenant_id},
                )
            )
            .mappings()
            .all()
        )
        candidates = [
            (r["name"], await effective_settings(session, tenant_id, r["id"], legal_entity_id))
            for r in rows
        ]
    words = {
        "hire": "New employees for this company are onboarded",
        "job_change": "Job changes for this employee are made",
        "exit": "Exits for this employee are made",
        "rehire": "Rehires for this employee are made",
    }
    for name, settings in candidates:
        if getattr(settings.lifecycle, operation) == "APP":
            raise CodedHTTPException(403, f"{words[operation]} in {name}.", code="MANAGED_BY_APP")


async def field_control(
    session: AsyncSession, tenant_id: UUID, employment_id: UUID
) -> list[dict[str, Any]]:
    """For each catalogue field: who owns it, whether it is locked in HRMS, and how to override."""
    apps = await linked_apps(session, tenant_id, employment_id)
    out = []
    for field in OWNABLE_FIELDS:
        owner_app = next((a for a in apps if a.settings.owner(field) == "APP"), None)
        shared = any(a.settings.owner(field) == "SHARED" for a in apps)
        out.append(
            {
                "field": field,
                "label": FIELDS[field]["label"],
                "owner": owner_app.code if owner_app else ("SHARED" if shared else "HRMS"),
                "owner_name": owner_app.name if owner_app else None,
                "locked": owner_app is not None,
                "override": owner_app.settings.hr_override if owner_app else None,
                "external_ids": {a.code: a.external_id for a in apps},
            }
        )
    return out

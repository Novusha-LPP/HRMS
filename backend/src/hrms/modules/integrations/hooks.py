"""
Where HRMS's own write paths tell connected apps about a change.

- personnel_action_applied(): called by people.router._apply_personnel_action, so every hire,
  rehire, job change and separation is announced however it happened (an HR screen, the
  scheduler on the effective date, or the sync API).
- personnel_action_scheduled(): a future-dated hire is announced when it is entered (apps may
  need the new joiner before day one); a future-dated separation is announced as an update.
- employee_changed.before/after(): profile edits outside personnel actions.

Each does nothing beyond one EXISTS query when the tenant has no connected app.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.integrations.events import (
    emit_employee_event,
    employee_snapshot,
    has_receiving_apps,
)

DIFF_FIELDS = (
    "employee_code",
    "first_name",
    "last_name",
    "preferred_name",
    "email",
    "mobile",
    "date_of_birth",
    "gender",
    "company",
    "department",
    "location",
    "designation",
    "manager",
    "role",
    "hire_date",
    "last_working_day",
    "employment_state",
)


def origin_of(idempotency_key: str | None) -> UUID | None:
    """The app that made a change through the sync API (see service._action_key)."""
    if idempotency_key and idempotency_key.startswith("int:"):
        try:
            return UUID(idempotency_key.split(":")[1])
        except (ValueError, IndexError):
            return None
    return None


def _simple(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("name") or value.get("employee_code") or value.get("id")
    return value


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    if not before or not after:
        return {}
    out = {}
    for field in DIFF_FIELDS:
        old, new = _simple(before.get(field)), _simple(after.get(field))
        if old != new:
            out[field] = {"old": old, "new": new}
    return out


async def capture(session: AsyncSession, tenant_id: UUID, employment_id: UUID) -> dict | None:
    if not await has_receiving_apps(session, tenant_id):
        return None
    return await employee_snapshot(session, tenant_id, employment_id)


async def personnel_action_applied(
    session: AsyncSession, tenant_id: UUID, pa, emp, before: dict | None
) -> None:
    if before is None and not await has_receiving_apps(session, tenant_id):
        return
    origin = origin_of(pa.idempotency_key)
    kind = str(pa.type)
    if kind == "HIRE":
        announced = (
            await session.execute(
                text("""SELECT integration_announced_at FROM personnel_actions
                        WHERE tenant_id = :tid AND id = :id"""),
                {"tid": tenant_id, "id": pa.id},
            )
        ).scalar()
        if announced is None:
            await emit_employee_event(
                session, tenant_id, emp.id, "employee.hired", origin_app_id=origin
            )
            await _mark_announced(session, tenant_id, pa.id)
        return
    after = await employee_snapshot(session, tenant_id, emp.id)
    changes = diff(before, after)
    if kind == "REHIRE":
        await emit_employee_event(
            session, tenant_id, emp.id, "employee.rehired", changes=changes, origin_app_id=origin
        )
    elif kind == "SEPARATION":
        await emit_employee_event(
            session, tenant_id, emp.id, "employee.separated", changes=changes, origin_app_id=origin
        )
    elif changes:
        await emit_employee_event(
            session, tenant_id, emp.id, "employee.updated", changes=changes, origin_app_id=origin
        )
        if "manager" in changes:
            await emit_employee_event(
                session,
                tenant_id,
                emp.id,
                "employee.manager_changed",
                changes={"manager": changes["manager"]},
                origin_app_id=origin,
            )


async def _mark_announced(session: AsyncSession, tenant_id: UUID, action_id: UUID) -> None:
    await session.execute(
        text("""UPDATE personnel_actions SET integration_announced_at = now()
                WHERE tenant_id = :tid AND id = :id"""),
        {"tid": tenant_id, "id": action_id},
    )


async def personnel_action_scheduled(session: AsyncSession, tenant_id: UUID, pa, emp) -> None:
    if not await has_receiving_apps(session, tenant_id):
        return
    origin = origin_of(pa.idempotency_key)
    kind = str(pa.type)
    if kind == "HIRE":
        event_id = await emit_employee_event(
            session,
            tenant_id,
            emp.id,
            "employee.hired",
            origin_app_id=origin,
            pending_placement=pa.changes or {},
        )
        if event_id is not None:
            await _mark_announced(session, tenant_id, pa.id)
    elif kind == "SEPARATION":
        await emit_employee_event(
            session,
            tenant_id,
            emp.id,
            "employee.updated",
            changes={"last_working_day": {"old": None, "new": pa.effective_date.isoformat()}},
            origin_app_id=origin,
        )


class employee_changed:  # noqa: N801 - used as a namespace: employee_changed.before/after
    @staticmethod
    async def before(session: AsyncSession, tenant_id: UUID, employment_id: UUID) -> dict | None:
        return await capture(session, tenant_id, employment_id)

    @staticmethod
    async def after(
        session: AsyncSession, tenant_id: UUID, employment_id: UUID, before: dict | None
    ) -> None:
        if before is None:
            return
        after = await employee_snapshot(session, tenant_id, employment_id)
        changes = diff(before, after)
        if changes:
            await emit_employee_event(
                session, tenant_id, employment_id, "employee.updated", changes=changes
            )
            if "manager" in changes:
                await emit_employee_event(
                    session,
                    tenant_id,
                    employment_id,
                    "employee.manager_changed",
                    changes={"manager": changes["manager"]},
                )


# ─── Onboarding checklist tasks (plan §9.5) ──────────────────────────────────


async def add_onboarding_tasks(
    session: AsyncSession, tenant_id: UUID, case_id: UUID, employment_id: UUID, hire_date
) -> int:
    """
    One "Set up in <app>" task per connected app that receives this new joiner. It ticks
    itself when the app has them: a two-way app when it links the employee, any other app
    when its events feed confirms the hire. Not required, so an outside system that is down
    never blocks onboarding; HR sees it open instead.
    """
    from uuid import uuid4

    from hrms.modules.integrations.events import in_people
    from hrms.modules.integrations.profiles import effective_settings

    if not await has_receiving_apps(session, tenant_id):
        return 0
    document = await employee_snapshot(session, tenant_id, employment_id)
    if document is None:
        return 0
    apps = (
        (
            await session.execute(
                text("""
                SELECT id, name, kind FROM connected_apps
                WHERE tenant_id = :tid AND status IN ('ACTIVE', 'PAUSED') ORDER BY code
            """),
                {"tid": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    added = 0
    for index, app in enumerate(apps):
        settings = await effective_settings(
            session, tenant_id, app["id"], UUID(document["_legal_entity_id"])
        )
        if "employee.hired" not in settings.outbound.events or not in_people(settings, document):
            continue
        linked = (
            await session.execute(
                text("""SELECT 1 FROM external_identities WHERE tenant_id = :tid
                        AND app_id = :app AND employment_id = :eid"""),
                {"tid": tenant_id, "app": app["id"], "eid": employment_id},
            )
        ).first()
        description = (
            f"Ticks itself when {app['name']} links this employee to its own record."
            if app["kind"] == "TWO_WAY"
            else f"Ticks itself when {app['name']} has received the new joiner."
        )
        await session.execute(
            text("""
            INSERT INTO onboarding_items
                (tenant_id, id, case_id, title, description, item_type, assignee_type, due_date,
                 required, sequence, status, completed_at, integration_app_id, recorded_at,
                 version)
            VALUES (:tid, :id, :case, :title, :descr, 'IT_SETUP', 'IT', :due, false, :seq,
                    :status, :done, :app, now(), 0)
        """),
            {
                "tid": tenant_id,
                "id": uuid4(),
                "case": case_id,
                "title": f"Set up in {app['name']}",
                "descr": description,
                "due": hire_date,
                "seq": 900 + index,
                "status": "COMPLETED" if linked and app["kind"] == "TWO_WAY" else "PENDING",
                "done": datetime_now() if linked and app["kind"] == "TWO_WAY" else None,
                "app": app["id"],
            },
        )
        added += 1
    return added


def datetime_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def complete_onboarding_tasks(
    session: AsyncSession, tenant_id: UUID, app_id: UUID, employment_ids: list[UUID] | None = None
) -> None:
    """Tick the app's open "Set up in" tasks for these employees (all confirmed ones if None)."""
    if employment_ids is not None and not employment_ids:
        return
    await session.execute(
        text(f"""
        UPDATE onboarding_items oi SET status = 'COMPLETED', completed_at = now(),
               version = oi.version + 1
        FROM onboarding_cases oc
        WHERE oi.tenant_id = :tid AND oi.integration_app_id = :app
          AND oi.status IN ('PENDING', 'IN_PROGRESS', 'OVERDUE')
          AND oc.tenant_id = oi.tenant_id AND oc.id = oi.case_id
          AND {
            "oc.employment_id = ANY(CAST(:eids AS uuid[]))"
            if employment_ids is not None
            else "true"
        }
    """),
        {
            "tid": tenant_id,
            "app": app_id,
            "eids": [str(e) for e in employment_ids or []],
        },
    )

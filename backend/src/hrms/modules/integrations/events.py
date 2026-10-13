"""
The outbox and the events feed (plan §7.8, §9.3, §9.5).

emit_employee_event() is called inside the transaction that makes the change, so an event
exists exactly when the change committed. It snapshots the employee, then fans the event out
to every connected app that should receive it, each under that app's own settings:

- events and people the app is not given are never fanned out to it;
- the app that made the change does not get its own change back;
- a new joiner is held until the app's delivery timing (on save, N days before joining, on
  joining), and anything later about that person waits behind the held hire.

An app's feed position (seq) is assigned when an event becomes available to it. read_feed()
returns only rows whose assigning transaction is older than every transaction still running
(pg_snapshot_xmin), so a transaction that took seq 101 but commits after seq 102 can never be
skipped by a reader that has already moved past 101.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.datetime_utils import business_today, safe_tz
from hrms.core.ids import to_typed_id
from hrms.modules.integrations.catalog import FIELDS, IntegrationSettings
from hrms.modules.integrations.profiles import effective_settings

FEED_RETENTION_DAYS = 30

# One query shape for one employee or a page of them. Column names are the catalogue's.
SNAPSHOT_SQL = """
    SELECT
        e.id AS employment_id, e.employee_number AS employee_code, e.hire_date,
        e.separation_date AS last_working_day, e.employment_state, e.legal_entity_id,
        le.name AS company_name, le.short_name AS company_code,
        p.legal_first_name AS first_name, p.legal_last_name AS last_name, p.preferred_name,
        p.date_of_birth, p.gender,
        ua.email, ua.mobile,
        CASE WHEN EXISTS (
            SELECT 1 FROM role_assignments ra JOIN roles r
              ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
            WHERE ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
              AND r.name = 'MANAGER'
        ) THEN 'MANAGER' ELSE 'EMPLOYEE' END AS role,
        a.org_unit_id, ou.name AS department_name, ou.code AS department_code,
        a.location_id, l.name AS location_name,
        a.job_id, j.title AS designation_name, j.code AS designation_code,
        am.manager_employment_id, me.employee_number AS manager_code,
        (SELECT COALESCE(json_object_agg(ca.code, x.external_id), '{}')
         FROM external_identities x JOIN connected_apps ca
           ON ca.tenant_id = x.tenant_id AND ca.id = x.app_id
         WHERE x.tenant_id = e.tenant_id AND x.employment_id = e.id) AS external_ids,
        (SELECT COALESCE(json_object_agg(ca.code, x.external_id), '{}')
         FROM external_identities x JOIN connected_apps ca
           ON ca.tenant_id = x.tenant_id AND ca.id = x.app_id
         WHERE x.tenant_id = e.tenant_id AND x.employment_id = am.manager_employment_id)
            AS manager_external_ids
    FROM employments e
    JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
    JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
    LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
    LEFT JOIN LATERAL (
        SELECT * FROM assignments a
        WHERE a.tenant_id = e.tenant_id AND a.employment_id = e.id
          AND a.effective_from <= :today
        ORDER BY (a.effective_to IS NULL OR a.effective_to > :today) DESC, a.effective_from DESC
        LIMIT 1
    ) a ON TRUE
    LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
    LEFT JOIN locations l ON l.tenant_id = a.tenant_id AND l.id = a.location_id
    LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
    LEFT JOIN LATERAL (
        SELECT am.manager_employment_id FROM assignment_managers am
        WHERE am.tenant_id = a.tenant_id AND am.assignment_id = a.id AND am.manager_type = 'LINE'
        ORDER BY am.effective_to IS NULL DESC, am.effective_from DESC
        LIMIT 1
    ) am ON TRUE
    LEFT JOIN employments me ON me.tenant_id = e.tenant_id AND me.id = am.manager_employment_id
"""


def _iso(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def snapshot_from_row(r: Any) -> dict[str, Any]:
    """The full employee document. filter_for_app() cuts it down to what one app may see."""
    external = (
        r["external_ids"]
        if isinstance(r["external_ids"], dict)
        else json.loads(r["external_ids"] or "{}")
    )
    manager_external = (
        r["manager_external_ids"]
        if isinstance(r["manager_external_ids"], dict)
        else json.loads(r["manager_external_ids"] or "{}")
    )
    return {
        "employment_id": to_typed_id("employment", r["employment_id"]),
        "employee_code": r["employee_code"],
        "first_name": r["first_name"],
        "last_name": r["last_name"],
        "preferred_name": r["preferred_name"],
        "email": r["email"],
        "mobile": r["mobile"],
        "date_of_birth": _iso(r["date_of_birth"]),
        "gender": r["gender"],
        "company": {
            "id": to_typed_id("legal_entity", r["legal_entity_id"]),
            "name": r["company_name"],
            "code": r["company_code"],
        },
        "department": (
            {
                "id": to_typed_id("org_unit", r["org_unit_id"]),
                "name": r["department_name"],
                "code": r["department_code"],
            }
            if r["org_unit_id"]
            else None
        ),
        "location": (
            {"id": to_typed_id("location", r["location_id"]), "name": r["location_name"]}
            if r["location_id"]
            else None
        ),
        "designation": (
            {
                "id": to_typed_id("job", r["job_id"]),
                "name": r["designation_name"],
                "code": r["designation_code"],
            }
            if r["job_id"]
            else None
        ),
        "manager": (
            {
                "employment_id": to_typed_id("employment", r["manager_employment_id"]),
                "employee_code": r["manager_code"],
                "external_ids": manager_external,
            }
            if r["manager_employment_id"]
            else None
        ),
        "role": r["role"],
        "hire_date": _iso(r["hire_date"]),
        "last_working_day": _iso(r["last_working_day"]),
        "employment_state": r["employment_state"],
        "external_ids": external,
        "_legal_entity_id": str(r["legal_entity_id"]),
        "_org_unit_id": str(r["org_unit_id"]) if r["org_unit_id"] else None,
    }


async def employee_snapshot(
    session: AsyncSession, tenant_id: UUID, employment_id: UUID
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(f"{SNAPSHOT_SQL} WHERE e.tenant_id = :tid AND e.id = :eid"),
                {"tid": tenant_id, "eid": employment_id, "today": business_today()},
            )
        )
        .mappings()
        .first()
    )
    return snapshot_from_row(row) if row else None


def allowed_fields(settings: IntegrationSettings) -> set[str]:
    out = settings.outbound
    by_class = {f for f, meta in FIELDS.items() if meta["data_class"] in out.data_classes}
    return by_class & set(out.fields) if out.fields is not None else by_class


def filter_for_app(
    document: dict[str, Any] | None, settings: IntegrationSettings, app_code: str
) -> dict[str, Any] | None:
    """Only the fields this app is given; its own external ID; never the internal keys."""
    if document is None:
        return None
    fields = allowed_fields(settings)
    out: dict[str, Any] = {"employment_id": document["employment_id"]}
    for field in FIELDS:
        if field in fields and field in document:
            value = document[field]
            if field == "manager" and value:
                value = {
                    "employment_id": value["employment_id"],
                    "employee_code": value["employee_code"],
                    "external_id": (value.get("external_ids") or {}).get(app_code),
                }
            out[field] = value
    out["external_id"] = (document.get("external_ids") or {}).get(app_code)
    return out


def filter_changes(
    changes: dict[str, Any] | None, settings: IntegrationSettings
) -> dict[str, Any] | None:
    if not changes:
        return changes
    fields = allowed_fields(settings)
    kept = {k: v for k, v in changes.items() if k in fields}
    return kept or None


def in_people(settings: IntegrationSettings, document: dict[str, Any]) -> bool:
    out = settings.outbound
    if out.legal_entity_ids is not None:
        from hrms.core.ids import to_uuid

        allowed = {str(to_uuid(i)) for i in out.legal_entity_ids}
        if document.get("_legal_entity_id") not in allowed:
            return False
    if out.org_unit_ids is not None:
        from hrms.core.ids import to_uuid

        allowed = {str(to_uuid(i)) for i in out.org_unit_ids}
        if document.get("_org_unit_id") not in allowed:
            return False
    return True


async def _with_placement(
    session: AsyncSession, tenant_id: UUID, document: dict[str, Any], placement: dict[str, Any]
) -> None:
    from hrms.core.ids import to_uuid

    def as_uuid(value: Any) -> UUID | None:
        if not value:
            return None
        value = str(value)
        return to_uuid(value) if "_" in value else UUID(value)

    lookups = (
        ("org_unit_id", "department", "SELECT id, name, code FROM org_units", "org_unit"),
        ("location_id", "location", "SELECT id, name, NULL AS code FROM locations", "location"),
        ("job_id", "designation", "SELECT id, title AS name, code FROM jobs", "job"),
    )
    for key, field, sql, kind in lookups:
        target = as_uuid(placement.get(key))
        if target is None:
            continue
        row = (
            (
                await session.execute(
                    text(f"{sql} WHERE tenant_id = :tid AND id = :id"),
                    {"tid": tenant_id, "id": target},
                )
            )
            .mappings()
            .first()
        )
        if row:
            document[field] = {"id": to_typed_id(kind, row["id"]), "name": row["name"]}
            if kind != "location":
                document[field]["code"] = row["code"]
            if key == "org_unit_id":
                document["_org_unit_id"] = str(row["id"])
    manager = as_uuid(placement.get("manager_employment_id"))
    if manager is not None:
        row = (
            (
                await session.execute(
                    text("""
                    SELECT e.employee_number,
                           (SELECT COALESCE(json_object_agg(ca.code, x.external_id), '{}')
                            FROM external_identities x JOIN connected_apps ca
                              ON ca.tenant_id = x.tenant_id AND ca.id = x.app_id
                            WHERE x.tenant_id = e.tenant_id AND x.employment_id = e.id) AS ext
                    FROM employments e WHERE e.tenant_id = :tid AND e.id = :id
                """),
                    {"tid": tenant_id, "id": manager},
                )
            )
            .mappings()
            .first()
        )
        if row:
            document["manager"] = {
                "employment_id": to_typed_id("employment", manager),
                "employee_code": row["employee_number"],
                "external_ids": row["ext"]
                if isinstance(row["ext"], dict)
                else json.loads(row["ext"]),
            }


async def _tenant_tz(session: AsyncSession, tenant_id: UUID):
    tz = (
        await session.execute(
            text("SELECT timezone FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    return safe_tz(tz or "Asia/Kolkata")


async def _available_at(
    session: AsyncSession,
    tenant_id: UUID,
    settings: IntegrationSettings,
    event_type: str,
    joining: date | None,
) -> datetime:
    now = datetime.now(UTC)
    timing = settings.outbound.timing
    if event_type != "employee.hired" or joining is None or timing.mode == "ON_SAVE":
        return now
    days = timing.days if timing.mode == "DAYS_BEFORE_JOIN" else 0
    start = datetime.combine(
        joining - timedelta(days=days), time.min, await _tenant_tz(session, tenant_id)
    )
    return max(now, start.astimezone(UTC))


async def has_receiving_apps(session: AsyncSession, tenant_id: UUID) -> bool:
    return bool(
        (
            await session.execute(
                text("""
                SELECT EXISTS (SELECT 1 FROM connected_apps
                               WHERE tenant_id = :tid AND status IN ('ACTIVE', 'PAUSED'))
            """),
                {"tid": tenant_id},
            )
        ).scalar()
    )


async def emit_employee_event(
    session: AsyncSession,
    tenant_id: UUID,
    employment_id: UUID,
    event_type: str,
    *,
    changes: dict[str, Any] | None = None,
    origin_app_id: UUID | None = None,
    pending_placement: dict[str, Any] | None = None,
) -> int | None:
    """
    Record one employee event and fan it out. Returns the event id, or None if no app listens.
    pending_placement: a future-dated hire's placement (personnel-action changes), shown in the
    document because the assignment itself only exists from the hire date.
    """
    if not await has_receiving_apps(session, tenant_id):
        return None
    if origin_app_id is None:
        origin_app_id = session.info.get("integration_origin_app_id")
    document = await employee_snapshot(session, tenant_id, employment_id)
    if document is None:
        return None
    if pending_placement:
        await _with_placement(session, tenant_id, document, pending_placement)
    joining = date.fromisoformat(document["hire_date"]) if document.get("hire_date") else None
    event_id = (
        await session.execute(
            text("""
            INSERT INTO integration_events
                (tenant_id, event_type, employment_id, payload, changes, origin_app_id,
                 joining_date)
            VALUES (:tid, :type, :eid, CAST(:payload AS jsonb), CAST(:changes AS jsonb), :origin,
                    :joining)
            RETURNING id
        """),
            {
                "tid": tenant_id,
                "type": event_type,
                "eid": employment_id,
                "payload": json.dumps(document),
                "changes": json.dumps(changes) if changes else None,
                "origin": origin_app_id,
                "joining": joining,
            },
        )
    ).scalar_one()

    apps = (
        (
            await session.execute(
                text("""
                SELECT id, code FROM connected_apps
                WHERE tenant_id = :tid AND status IN ('ACTIVE', 'PAUSED')
            """),
                {"tid": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    legal_entity_id = UUID(document["_legal_entity_id"])
    for app in apps:
        if app["id"] == origin_app_id:
            continue
        settings = await effective_settings(session, tenant_id, app["id"], legal_entity_id)
        if event_type not in settings.outbound.events or not in_people(settings, document):
            continue
        held_hire = (
            await session.execute(
                text("""
                SELECT ae.available_at, ae.event_id FROM integration_app_events ae
                JOIN integration_events ev ON ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id
                WHERE ae.tenant_id = :tid AND ae.app_id = :app AND ae.seq IS NULL
                  AND ev.employment_id = :eid AND ev.event_type = 'employee.hired'
                ORDER BY ae.event_id DESC LIMIT 1
            """),
                {"tid": tenant_id, "app": app["id"], "eid": employment_id},
            )
        ).first()
        if event_type == "employee.hire_cancelled" and held_hire:
            # The app never heard of this hire, so it never hears of the cancellation either.
            await session.execute(
                text("""
                DELETE FROM integration_app_events ae USING integration_events ev
                WHERE ae.tenant_id = :tid AND ae.app_id = :app AND ae.seq IS NULL
                  AND ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id
                  AND ev.employment_id = :eid
            """),
                {"tid": tenant_id, "app": app["id"], "eid": employment_id},
            )
            continue
        if held_hire:
            available = held_hire.available_at
        else:
            available = await _available_at(session, tenant_id, settings, event_type, joining)
        if available <= datetime.now(UTC) and not held_hire:
            await session.execute(
                text("""
                INSERT INTO integration_app_events
                    (tenant_id, app_id, event_id, seq, assigned_txid, available_at)
                VALUES (:tid, :app, :ev, nextval('integration_feed_seq'), pg_current_xact_id(),
                        :at)
            """),
                {"tid": tenant_id, "app": app["id"], "ev": event_id, "at": available},
            )
        else:
            await session.execute(
                text("""
                INSERT INTO integration_app_events (tenant_id, app_id, event_id, available_at)
                VALUES (:tid, :app, :ev, :at)
            """),
                {"tid": tenant_id, "app": app["id"], "ev": event_id, "at": available},
            )
    return int(event_id)


async def reschedule_held_hire(session: AsyncSession, tenant_id: UUID, employment_id: UUID) -> None:
    """The joining date moved: move every app's held hire (and what waits behind it) with it."""
    held = (
        (
            await session.execute(
                text("""
                SELECT DISTINCT ae.app_id FROM integration_app_events ae
                JOIN integration_events ev ON ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id
                WHERE ae.tenant_id = :tid AND ae.seq IS NULL AND ev.employment_id = :eid
            """),
                {"tid": tenant_id, "eid": employment_id},
            )
        )
        .scalars()
        .all()
    )
    if not held:
        return
    document = await employee_snapshot(session, tenant_id, employment_id)
    if not document:
        return
    joining = date.fromisoformat(document["hire_date"])
    for app_id in held:
        settings = await effective_settings(
            session, tenant_id, app_id, UUID(document["_legal_entity_id"])
        )
        at = await _available_at(session, tenant_id, settings, "employee.hired", joining)
        await session.execute(
            text("""
            UPDATE integration_app_events ae SET available_at = :at
            FROM integration_events ev
            WHERE ae.tenant_id = :tid AND ae.app_id = :app AND ae.seq IS NULL
              AND ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id AND ev.employment_id = :eid
        """),
            {"tid": tenant_id, "app": app_id, "eid": employment_id, "at": at},
        )


async def release_due(session: AsyncSession, tenant_id: UUID, app_id: UUID | None = None) -> int:
    """Give held events whose time has come a feed position, in event order."""
    rows = (
        await session.execute(
            text(f"""
            SELECT app_id, event_id FROM integration_app_events
            WHERE tenant_id = :tid AND seq IS NULL AND available_at <= now()
              {"AND app_id = :app" if app_id else ""}
            ORDER BY event_id
            FOR UPDATE SKIP LOCKED
        """),
            {"tid": tenant_id, "app": app_id},
        )
    ).all()
    for row in rows:
        await session.execute(
            text("""
            UPDATE integration_app_events
            SET seq = nextval('integration_feed_seq'), assigned_txid = pg_current_xact_id()
            WHERE tenant_id = :tid AND app_id = :app AND event_id = :ev
        """),
            {"tid": tenant_id, "app": row.app_id, "ev": row.event_id},
        )
    return len(rows)


def encode_cursor(position: int) -> str:
    return f"c_{position:012d}"


def decode_cursor(cursor: str | None) -> int:
    if not cursor or cursor == "0":
        return 0
    try:
        if not cursor.startswith("c_"):
            raise ValueError
        return int(cursor[2:])
    except ValueError as exc:
        from hrms.core.errors import CodedHTTPException

        raise CodedHTTPException(422, "Invalid cursor", code="INVALID_CURSOR") from exc


async def read_feed(
    session: AsyncSession,
    tenant_id: UUID,
    app_id: UUID,
    app_code: str,
    after: int,
    limit: int,
    legal_entity_ids: frozenset[UUID] | None = None,
) -> dict[str, Any]:
    """
    legal_entity_ids: the key's company limit. Events about employees of other companies are
    skipped (the cursor still moves past them).
    """
    from hrms.core.errors import CodedHTTPException

    purged = (
        await session.execute(
            text("""
            SELECT purged_through FROM integration_cursors WHERE tenant_id = :tid AND app_id = :app
        """),
            {"tid": tenant_id, "app": app_id},
        )
    ).scalar() or 0
    if after < purged:
        # Never behind the purge point, or a reader told to resync would be told again.
        latest = max(await _latest_visible(session, tenant_id, app_id), purged)
        raise CodedHTTPException(
            410,
            "Events after this cursor are older than the feed keeps. Reload with "
            "GET /v1/integrations/employees, then continue from the cursor in the "
            "X-Resync-Cursor header.",
            code="RESYNC_REQUIRED",
            headers={"X-Resync-Cursor": encode_cursor(latest)},
        )
    rows = (
        (
            await session.execute(
                text("""
                SELECT ae.seq, ev.id, ev.event_type, ev.employment_id, ev.payload, ev.changes,
                       ev.occurred_at, ev.joining_date
                FROM integration_app_events ae
                JOIN integration_events ev ON ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id
                WHERE ae.tenant_id = :tid AND ae.app_id = :app AND ae.seq > :after
                  AND ae.seq IS NOT NULL
                  AND ae.assigned_txid < pg_snapshot_xmin(pg_current_snapshot())
                ORDER BY ae.seq
                LIMIT :limit
            """),
                {"tid": tenant_id, "app": app_id, "after": after, "limit": limit + 1},
            )
        )
        .mappings()
        .all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    events = []
    for r in rows:
        document = r["payload"]
        if legal_entity_ids is not None and (
            UUID(document["_legal_entity_id"]) not in legal_entity_ids
        ):
            continue
        settings = await effective_settings(
            session, tenant_id, app_id, UUID(document["_legal_entity_id"])
        )
        events.append(
            {
                "id": f"evt_{r['id']}",
                "event": r["event_type"],
                "occurred_at": r["occurred_at"].isoformat(),
                "employment_id": document["employment_id"],
                "external_id": (document.get("external_ids") or {}).get(app_code),
                "employee": filter_for_app(document, settings, app_code),
                "changes": filter_changes(r["changes"], settings),
            }
        )
    position = rows[-1]["seq"] if rows else after
    # The cursor an app sends confirms it has everything before it, so that (not what this
    # page returns) is what is recorded as the app's position.
    await session.execute(
        text("""
        INSERT INTO integration_cursors (tenant_id, app_id, position, read_at)
        VALUES (:tid, :app, :pos, now())
        ON CONFLICT (tenant_id, app_id)
        DO UPDATE SET position = GREATEST(integration_cursors.position, EXCLUDED.position),
                      read_at = now()
    """),
        {"tid": tenant_id, "app": app_id, "pos": after},
    )
    if after:
        await _tick_confirmed_hires(session, tenant_id, app_id, after)
    return {"events": events, "next_cursor": encode_cursor(position), "has_more": has_more}


async def _tick_confirmed_hires(
    session: AsyncSession, tenant_id: UUID, app_id: UUID, confirmed: int
) -> None:
    """An app other than a two-way one 'has' a new joiner once it confirms the hire event."""
    kind = (
        await session.execute(
            text("SELECT kind FROM connected_apps WHERE tenant_id = :tid AND id = :app"),
            {"tid": tenant_id, "app": app_id},
        )
    ).scalar()
    if kind == "TWO_WAY":
        return  # confirmed by linking, not by reading
    employments = (
        (
            await session.execute(
                text("""
                SELECT DISTINCT ev.employment_id FROM integration_app_events ae
                JOIN integration_events ev ON ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id
                JOIN onboarding_cases oc ON oc.tenant_id = ev.tenant_id
                 AND oc.employment_id = ev.employment_id
                JOIN onboarding_items oi ON oi.tenant_id = oc.tenant_id AND oi.case_id = oc.id
                 AND oi.integration_app_id = ae.app_id AND oi.status <> 'COMPLETED'
                WHERE ae.tenant_id = :tid AND ae.app_id = :app AND ae.seq IS NOT NULL
                  AND ae.seq <= :pos AND ev.event_type = 'employee.hired'
            """),
                {"tid": tenant_id, "app": app_id, "pos": confirmed},
            )
        )
        .scalars()
        .all()
    )
    if employments:
        from hrms.modules.integrations.hooks import complete_onboarding_tasks

        await complete_onboarding_tasks(session, tenant_id, app_id, list(employments))


async def _latest_visible(session: AsyncSession, tenant_id: UUID, app_id: UUID) -> int:
    return (
        await session.execute(
            text("""
            SELECT COALESCE(MAX(seq), 0) FROM integration_app_events
            WHERE tenant_id = :tid AND app_id = :app AND seq IS NOT NULL
              AND assigned_txid < pg_snapshot_xmin(pg_current_snapshot())
        """),
            {"tid": tenant_id, "app": app_id},
        )
    ).scalar_one()


async def purge_old_events(session: AsyncSession, tenant_id: UUID) -> int:
    """Retention: drop delivered events older than the feed keeps, remembering where per app."""
    cutoff = datetime.now(UTC) - timedelta(days=FEED_RETENTION_DAYS)
    await session.execute(
        text("""
        INSERT INTO integration_cursors (tenant_id, app_id, purged_through)
        SELECT ae.tenant_id, ae.app_id, MAX(ae.seq)
        FROM integration_app_events ae
        JOIN integration_events ev ON ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id
        WHERE ae.tenant_id = :tid AND ae.seq IS NOT NULL AND ev.occurred_at < :cutoff
        GROUP BY ae.tenant_id, ae.app_id
        ON CONFLICT (tenant_id, app_id) DO UPDATE
        SET purged_through = GREATEST(integration_cursors.purged_through, EXCLUDED.purged_through)
    """),
        {"tid": tenant_id, "cutoff": cutoff},
    )
    deleted = await session.execute(
        text("""
        DELETE FROM integration_events ev
        WHERE ev.tenant_id = :tid AND ev.occurred_at < :cutoff
          AND NOT EXISTS (SELECT 1 FROM integration_app_events ae
                          WHERE ae.tenant_id = ev.tenant_id AND ae.event_id = ev.id
                            AND ae.seq IS NULL)
    """),
        {"tid": tenant_id, "cutoff": cutoff},
    )
    return getattr(deleted, "rowcount", 0) or 0

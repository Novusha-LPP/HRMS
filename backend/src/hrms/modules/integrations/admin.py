"""
/v1/admin/integrations/* — Settings → Integrations, for the tenant administrator (plan §14).

integrations.manage covers apps, keys and the sync log; integrations.configure covers settings,
mappings, duplicates and held exits. Both are held only by SUPER_ADMIN today (its "*" grant),
which already requires MFA; the role builder (enterprise plan F1) will let them be granted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, read_scope, require_global_permission
from hrms.core.change_audit import record_change
from hrms.core.database import SessionDep
from hrms.core.errors import CodedHTTPException
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.integrations import catalog, events, profiles
from hrms.modules.integrations.keys import (
    SCOPES,
    IntegrationContext,
    generate_key,
    hash_key,
    key_environment,
)
from hrms.modules.integrations.ownership import field_control
from hrms.modules.integrations.schemas import (
    AppCreate,
    AppResponse,
    AppUpdate,
    DuplicateResolve,
    HeldExitDecision,
    KeyCreate,
    KeyCreated,
    KeyResponse,
    KeyRevoke,
    MappingCreate,
    MappingResponse,
    ProfileCreate,
    ProfilePublish,
    ProfileResponse,
    ProfileUpdate,
)

router = APIRouter(prefix="/v1/admin/integrations", tags=["Integration settings"])
employee_router = APIRouter(tags=["Integration settings"])

MANAGE = require_global_permission("integrations.manage")
CONFIGURE = require_global_permission("integrations.configure")


async def _app(session, tenant_id: UUID, app_id: str) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM connected_apps WHERE tenant_id = :tid AND id = :id"),
                {"tid": tenant_id, "id": to_uuid(app_id)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "App not found")
    return dict(row)


# ─── Catalogue ───────────────────────────────────────────────────────────────


@router.get("/catalog", dependencies=[MANAGE])
async def integration_catalog() -> dict[str, Any]:
    """Everything the screens need to render the settings: fields, presets, scopes, options."""
    return {
        "fields": [
            {"field": f, **meta, "ownable": f in catalog.OWNABLE_FIELDS}
            for f, meta in catalog.FIELDS.items()
        ],
        "presets": [
            {
                "id": key,
                "label": p["label"],
                "description": p["description"],
                "field_ownership": p["field_ownership"],
            }
            for key, p in catalog.PRESETS.items()
        ],
        "scopes": [{"scope": k, "description": v} for k, v in SCOPES.items()],
        "events": list(catalog.EVENT_TYPES),
        "data_classes": ["BASIC", "CONTACT", "PERSONAL", "ATTENDANCE_LEAVE"],
        "defaults": {
            "TWO_WAY": catalog.defaults_for("TWO_WAY"),
            "RECEIVE_ONLY": catalog.defaults_for("RECEIVE_ONLY"),
            "READ_ONLY": catalog.defaults_for("READ_ONLY"),
        },
        "key_environment": key_environment(),
    }


# ─── Apps ────────────────────────────────────────────────────────────────────


async def _app_response(session, tenant_id: UUID, row: dict[str, Any]) -> AppResponse:
    stats = (
        (
            await session.execute(
                text("""
                SELECT
                  (SELECT count(*) FROM external_identities WHERE tenant_id = :tid AND app_id = :id)
                      AS linked,
                  (SELECT count(*) FROM api_keys WHERE tenant_id = :tid AND app_id = :id
                     AND is_active AND revoked_at IS NULL
                     AND (expires_at IS NULL OR expires_at > now())) AS keys,
                  (SELECT max(created_at) FROM integration_requests
                     WHERE tenant_id = :tid AND app_id = :id) AS last_request,
                  (SELECT position FROM integration_cursors WHERE tenant_id = :tid AND app_id = :id)
                      AS position,
                  (SELECT read_at FROM integration_cursors WHERE tenant_id = :tid AND app_id = :id)
                      AS read_at,
                  (SELECT count(*) FROM integration_app_events ae WHERE ae.tenant_id = :tid
                     AND ae.app_id = :id AND ae.seq IS NOT NULL
                     AND ae.seq > COALESCE((SELECT position FROM integration_cursors c
                                            WHERE c.tenant_id = :tid AND c.app_id = :id), 0))
                      AS lag
            """),
                {"tid": tenant_id, "id": row["id"]},
            )
        )
        .mappings()
        .one()
    )
    return AppResponse(
        id=to_typed_id("connected_app", row["id"]),
        code=row["code"],
        name=row["name"],
        kind=row["kind"],
        status=row["status"],
        created_at=row["created_at"],
        linked_employees=stats["linked"],
        active_keys=stats["keys"],
        last_request_at=stats["last_request"],
        feed_position=events.encode_cursor(stats["position"]) if stats["position"] else None,
        feed_read_at=stats["read_at"],
        feed_lag=stats["lag"],
    )


@router.get("/apps", response_model=list[AppResponse], dependencies=[MANAGE])
async def list_apps(tenant_id: TenantDep, session: SessionDep) -> list[AppResponse]:
    rows = (
        (
            await session.execute(
                text("""SELECT * FROM connected_apps WHERE tenant_id = :tid
                        ORDER BY status = 'DISCONNECTED', code"""),
                {"tid": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    return [await _app_response(session, tenant_id, dict(r)) for r in rows]


@router.post("/apps", response_model=AppResponse, status_code=201, dependencies=[MANAGE])
async def create_app(
    body: AppCreate, principal: CurrentUser, tenant_id: TenantDep, session: SessionDep
) -> AppResponse:
    code = body.code.upper()
    taken = (
        await session.execute(
            text("""SELECT 1 FROM connected_apps WHERE tenant_id = :tid AND code = :code
                    AND status <> 'DISCONNECTED'"""),
            {"tid": tenant_id, "code": code},
        )
    ).first()
    if taken:
        raise CodedHTTPException(
            409, f"An app with code {code} already exists", code="APP_CODE_IN_USE"
        )
    app_id = uuid4()
    await session.execute(
        text("""INSERT INTO connected_apps (tenant_id, id, code, name, kind, created_by)
                VALUES (:tid, :id, :code, :name, :kind, :by)"""),
        {
            "tid": tenant_id,
            "id": app_id,
            "code": code,
            "name": body.name,
            "kind": body.kind,
            "by": principal.user_account_id,
        },
    )
    await record_change(
        session,
        tenant_id,
        "connected_app",
        app_id,
        "CREATE",
        principal.user_account_id,
        None,
        {"code": code, "name": body.name, "kind": body.kind},
    )
    return await _app_response(
        session, tenant_id, await _app(session, tenant_id, to_typed_id("connected_app", app_id))
    )


@router.patch("/apps/{app_id}", response_model=AppResponse, dependencies=[MANAGE])
async def update_app(
    app_id: str,
    body: AppUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> AppResponse:
    app = await _app(session, tenant_id, app_id)
    if app["status"] == "DISCONNECTED":
        raise CodedHTTPException(
            409, "A disconnected app can't be changed", code="APP_DISCONNECTED"
        )
    changes: dict[str, Any] = {}
    if body.name is not None and body.name != app["name"]:
        changes["name"] = body.name
    if body.status is not None and body.status != app["status"]:
        changes["status"] = body.status
    if changes:
        await session.execute(
            text("""
            UPDATE connected_apps SET
                name = COALESCE(:name, name),
                status = COALESCE(:status, status),
                paused_at = CASE WHEN :status = 'PAUSED' THEN now()
                                 WHEN :status = 'ACTIVE' THEN NULL ELSE paused_at END,
                disconnected_at = CASE WHEN :status = 'DISCONNECTED' THEN now()
                                       ELSE disconnected_at END
            WHERE tenant_id = :tid AND id = :id
        """),
            {
                "tid": tenant_id,
                "id": app["id"],
                "name": changes.get("name"),
                "status": changes.get("status"),
            },
        )
        if changes.get("status") == "DISCONNECTED":
            # Disconnecting revokes every credential; the log and the links stay as history.
            await session.execute(
                text("""UPDATE api_keys SET is_active = false, revoked_at = now(),
                        revoked_by = :by, revoke_reason = 'App disconnected'
                        WHERE tenant_id = :tid AND app_id = :id AND revoked_at IS NULL"""),
                {"tid": tenant_id, "id": app["id"], "by": principal.user_account_id},
            )
        await record_change(
            session,
            tenant_id,
            "connected_app",
            app["id"],
            "UPDATE",
            principal.user_account_id,
            {k: app[k] for k in changes},
            changes,
        )
    return await _app_response(session, tenant_id, await _app(session, tenant_id, app_id))


# ─── Keys ────────────────────────────────────────────────────────────────────


def _key_response(r: dict[str, Any]) -> KeyResponse:
    now = datetime.now(UTC)
    if r["revoked_at"] is not None or not r["is_active"]:
        state = "REVOKED"
    elif r["expires_at"] is not None and r["expires_at"] <= now:
        state = "EXPIRED"
    else:
        state = "ACTIVE"
    return KeyResponse(
        id=to_typed_id("api_key", r["id"]),
        name=r["name"],
        prefix=r["key_prefix"],
        client_id=f"hrms_{r['environment']}_{r['key_prefix']}",
        environment=r["environment"],
        scopes=list(r["scopes"] or []),
        allowed_ips=r["allowed_ips"],
        legal_entity_ids=[to_typed_id("legal_entity", UUID(str(i))) for i in r["legal_entity_ids"]]
        if r["legal_entity_ids"]
        else None,
        status=state,
        expires_at=r["expires_at"],
        created_at=r["created_at"],
        last_used_at=r["last_used_at"],
        last_used_ip=r["last_used_ip"],
        calls_last_hour=int(r.get("calls_last_hour") or 0),
        rate_limit_per_minute=r["rate_limit_per_minute"],
        revoked_at=r["revoked_at"],
        revoke_reason=r["revoke_reason"],
    )


@router.get("/apps/{app_id}/keys", response_model=list[KeyResponse], dependencies=[MANAGE])
async def list_keys(app_id: str, tenant_id: TenantDep, session: SessionDep) -> list[KeyResponse]:
    app = await _app(session, tenant_id, app_id)
    rows = (
        (
            await session.execute(
                text("""
                SELECT k.*,
                       (SELECT COALESCE(sum(w.count), 0) FROM integration_rate_windows w
                        WHERE w.tenant_id = k.tenant_id AND w.api_key_id = k.id
                          AND w.window_start > now() - interval '1 hour') AS calls_last_hour
                FROM api_keys k WHERE k.tenant_id = :tid AND k.app_id = :app
                ORDER BY k.revoked_at IS NOT NULL, k.created_at DESC
            """),
                {"tid": tenant_id, "app": app["id"]},
            )
        )
        .mappings()
        .all()
    )
    return [_key_response(dict(r)) for r in rows]


@router.post(
    "/apps/{app_id}/keys", response_model=KeyCreated, status_code=201, dependencies=[MANAGE]
)
async def create_key(
    app_id: str,
    body: KeyCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> KeyCreated:
    import ipaddress

    app = await _app(session, tenant_id, app_id)
    if app["status"] == "DISCONNECTED":
        raise CodedHTTPException(409, "This app is disconnected", code="APP_DISCONNECTED")
    unknown = sorted(set(body.scopes) - set(SCOPES))
    if unknown:
        raise CodedHTTPException(422, f"Unknown scopes: {', '.join(unknown)}", code="UNKNOWN_SCOPE")
    writes = {"employees.sync", "passwords.sync", "sessions.issue"} & set(body.scopes)
    if writes and app["kind"] != "TWO_WAY":
        raise CodedHTTPException(
            422,
            f"A {app['kind'].lower().replace('_', '-')} app can't hold {', '.join(sorted(writes))}",
            code="SCOPE_NOT_ALLOWED",
        )
    for entry in body.allowed_ips or []:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise CodedHTTPException(
                422, f"Not an IP address or range: {entry}", code="INVALID_IP"
            ) from exc
    entities = None
    if body.legal_entity_ids is not None:
        entities = [str(to_uuid(i)) for i in body.legal_entity_ids]
    active = (
        await session.execute(
            text("""SELECT count(*) FROM api_keys WHERE tenant_id = :tid AND app_id = :app
                    AND is_active AND revoked_at IS NULL
                    AND (expires_at IS NULL OR expires_at > now())"""),
            {"tid": tenant_id, "app": app["id"]},
        )
    ).scalar_one()
    if active >= 2:
        raise CodedHTTPException(
            409,
            "An app can have two active keys (for switching without downtime). Revoke one first.",
            code="TOO_MANY_KEYS",
        )
    raw, prefix, _ = generate_key()
    key_id = uuid4()
    expires = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    )
    await session.execute(
        text("""
        INSERT INTO api_keys
            (tenant_id, id, app_id, name, key_prefix, key_hash, scopes, allowed_ips,
             legal_entity_ids, environment, expires_at, rate_limit_per_minute, created_by)
        VALUES (:tid, :id, :app, :name, :prefix, :hash, CAST(:scopes AS jsonb),
                CAST(:ips AS jsonb), CAST(:entities AS jsonb), :env, :expires, :rate, :by)
    """),
        {
            "tid": tenant_id,
            "id": key_id,
            "app": app["id"],
            "name": body.name,
            "prefix": prefix,
            "hash": hash_key(raw),
            "scopes": json.dumps(sorted(body.scopes)),
            "ips": json.dumps(body.allowed_ips) if body.allowed_ips else None,
            "entities": json.dumps(entities) if entities is not None else None,
            "env": key_environment(),
            "expires": expires,
            "rate": body.rate_limit_per_minute,
            "by": principal.user_account_id,
        },
    )
    await record_change(
        session,
        tenant_id,
        "api_key",
        key_id,
        "CREATE",
        principal.user_account_id,
        None,
        {
            "app": app["code"],
            "name": body.name,
            "prefix": prefix,
            "scopes": ",".join(sorted(body.scopes)),
        },
    )
    row = (
        (
            await session.execute(
                text("SELECT * FROM api_keys WHERE tenant_id = :tid AND id = :id"),
                {"tid": tenant_id, "id": key_id},
            )
        )
        .mappings()
        .one()
    )
    return KeyCreated(**_key_response(dict(row)).model_dump(), key=raw)


@router.post(
    "/apps/{app_id}/keys/{key_id}/revoke", response_model=KeyResponse, dependencies=[MANAGE]
)
async def revoke_key(
    app_id: str,
    key_id: str,
    body: KeyRevoke,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> KeyResponse:
    app = await _app(session, tenant_id, app_id)
    updated = (
        (
            await session.execute(
                text("""
                UPDATE api_keys SET is_active = false, revoked_at = COALESCE(revoked_at, now()),
                       revoked_by = COALESCE(revoked_by, :by),
                       revoke_reason = COALESCE(revoke_reason, :reason)
                WHERE tenant_id = :tid AND app_id = :app AND id = :id
                RETURNING *
            """),
                {
                    "tid": tenant_id,
                    "app": app["id"],
                    "id": to_uuid(key_id),
                    "by": principal.user_account_id,
                    "reason": body.reason,
                },
            )
        )
        .mappings()
        .first()
    )
    if not updated:
        raise HTTPException(404, "Key not found")
    await record_change(
        session,
        tenant_id,
        "api_key",
        updated["id"],
        "ARCHIVE",
        principal.user_account_id,
        {"status": "ACTIVE"},
        None,
    )
    return _key_response(dict(updated))


# ─── Settings ────────────────────────────────────────────────────────────────


def _profile_response(r: dict[str, Any]) -> ProfileResponse:
    return ProfileResponse(
        id=to_typed_id("integration_profile", r["id"]),
        app_id=to_typed_id("connected_app", r["app_id"]),
        legal_entity_id=to_typed_id("legal_entity", r["legal_entity_id"])
        if r["legal_entity_id"]
        else None,
        version=r["version"],
        status=r["status"],
        effective_from=r["effective_from"],
        settings=r["settings"],
        note=r["note"],
        created_at=r["created_at"],
        published_at=r["published_at"],
    )


async def _has_scheme(session, tenant_id: UUID, legal_entity_id: UUID | None) -> bool:
    return bool(
        (
            await session.execute(
                text("""SELECT 1 FROM employee_id_schemes WHERE tenant_id = :tid
                        AND archived_at IS NULL
                        AND (legal_entity_id IS NULL OR legal_entity_id = :le) LIMIT 1"""),
                {"tid": tenant_id, "le": legal_entity_id},
            )
        ).first()
    )


@router.get("/apps/{app_id}/settings", dependencies=[CONFIGURE])
async def get_settings(
    app_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    legal_entity_id: str | None = Query(default=None),
) -> dict[str, Any]:
    app = await _app(session, tenant_id, app_id)
    le = to_uuid(legal_entity_id) if legal_entity_id else None
    effective = await profiles.effective_settings(session, tenant_id, app["id"], le)
    override: dict[str, Any] = {}
    if le is not None:
        override = (
            await profiles._in_force(session, tenant_id, app["id"], le, profiles.business_today())
            or {}
        )
    return {
        "app_id": to_typed_id("connected_app", app["id"]),
        "legal_entity_id": legal_entity_id,
        "settings": effective.model_dump(),
        "overridden": catalog.overridden_paths(override),
        "warnings": profiles.health_warnings(
            effective, company_has_id_scheme=await _has_scheme(session, tenant_id, le)
        ),
    }


@router.get(
    "/apps/{app_id}/profiles", response_model=list[ProfileResponse], dependencies=[CONFIGURE]
)
async def list_profiles(
    app_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    legal_entity_id: str | None = Query(default=None),
) -> list[ProfileResponse]:
    app = await _app(session, tenant_id, app_id)
    rows = (
        (
            await session.execute(
                text("""SELECT * FROM integration_profiles WHERE tenant_id = :tid AND app_id = :app
                        AND legal_entity_id IS NOT DISTINCT FROM :le
                        ORDER BY version DESC"""),
                {
                    "tid": tenant_id,
                    "app": app["id"],
                    "le": to_uuid(legal_entity_id) if legal_entity_id else None,
                },
            )
        )
        .mappings()
        .all()
    )
    return [_profile_response(dict(r)) for r in rows]


@router.post(
    "/apps/{app_id}/profiles",
    response_model=ProfileResponse,
    status_code=201,
    dependencies=[CONFIGURE],
)
async def create_profile(
    app_id: str,
    body: ProfileCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> ProfileResponse:
    app = await _app(session, tenant_id, app_id)
    le = to_uuid(body.legal_entity_id) if body.legal_entity_id else None
    if body.settings is not None:
        document = body.settings
    elif le is not None:
        current = await profiles._in_force(
            session, tenant_id, app["id"], le, profiles.business_today()
        )
        document = dict(current or {}) if body.copy_from == "CURRENT" else {}
    else:
        document = await profiles.tenant_settings(session, tenant_id, app["id"])
    if body.preset:
        document = dict(document)
        document["field_ownership"] = dict(catalog.PRESETS[body.preset]["field_ownership"])
    profile_id = await profiles.create_draft(
        session,
        tenant_id,
        app["id"],
        le,
        document,
        created_by=principal.user_account_id,
        note=body.note,
    )
    return _profile_response(await profiles.load_profile(session, tenant_id, profile_id))


@router.put("/profiles/{profile_id}", response_model=ProfileResponse, dependencies=[CONFIGURE])
async def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    tenant_id: TenantDep,
    session: SessionDep,
) -> ProfileResponse:
    pid = to_uuid(profile_id)
    await profiles.update_draft(session, tenant_id, pid, body.settings, body.note)
    return _profile_response(await profiles.load_profile(session, tenant_id, pid))


@router.post(
    "/profiles/{profile_id}/discard", response_model=ProfileResponse, dependencies=[CONFIGURE]
)
async def discard_profile(profile_id: str, tenant_id: TenantDep, session: SessionDep):
    pid = to_uuid(profile_id)
    profile = await profiles.load_profile(session, tenant_id, pid)
    if profile["status"] != "DRAFT":
        raise CodedHTTPException(409, "Only a draft can be discarded", code="NOT_A_DRAFT")
    await session.execute(
        text(
            "UPDATE integration_profiles SET status = 'DISCARDED' WHERE tenant_id = :tid "
            "AND id = :id"
        ),
        {"tid": tenant_id, "id": pid},
    )
    return _profile_response(await profiles.load_profile(session, tenant_id, pid))


@router.post("/profiles/{profile_id}/preview", dependencies=[CONFIGURE])
async def preview_profile(profile_id: str, tenant_id: TenantDep, session: SessionDep):
    """What publishing this draft would change, before it is published (plan §6.3)."""
    pid = to_uuid(profile_id)
    profile = await profiles.load_profile(session, tenant_id, pid)
    app_id, le = profile["app_id"], profile["legal_entity_id"]
    current = await profiles.effective_settings(session, tenant_id, app_id, le)
    base = await profiles.tenant_settings(session, tenant_id, app_id)
    if le is not None:
        draft = catalog.validate_full(
            catalog.merge(
                catalog.merge(
                    base,
                    await profiles._in_force(
                        session, tenant_id, app_id, le, profiles.business_today()
                    )
                    or {},
                ),
                profile["settings"],
            )
        )
    else:
        draft = catalog.validate_full(catalog.merge(base, profile["settings"]))
    locked = sorted(
        f for f in catalog.OWNABLE_FIELDS if draft.owner(f) == "APP" and current.owner(f) != "APP"
    )
    unlocked = sorted(
        f for f in catalog.OWNABLE_FIELDS if current.owner(f) == "APP" and draft.owner(f) != "APP"
    )
    affected = (
        await session.execute(
            text("""SELECT count(*) FROM external_identities x
                    JOIN employments e ON e.tenant_id = x.tenant_id AND e.id = x.employment_id
                    WHERE x.tenant_id = :tid AND x.app_id = :app
                      AND (CAST(:le AS uuid) IS NULL OR e.legal_entity_id = :le)"""),
            {"tid": tenant_id, "app": app_id, "le": le},
        )
    ).scalar_one()
    recent_hr_edits = 0
    if locked:
        recent_hr_edits = (
            await session.execute(
                text("""
                SELECT count(DISTINCT ev.employment_id) FROM integration_events ev
                JOIN external_identities x ON x.tenant_id = ev.tenant_id
                  AND x.employment_id = ev.employment_id AND x.app_id = :app
                WHERE ev.tenant_id = :tid AND ev.origin_app_id IS NULL
                  AND ev.occurred_at > now() - interval '30 days'
                  AND ev.changes IS NOT NULL AND ev.changes ?| CAST(:fields AS text[])
            """),
                {"tid": tenant_id, "app": app_id, "fields": locked},
            )
        ).scalar_one()
    return {
        "linked_employees_affected": affected,
        "fields_becoming_locked": locked,
        "fields_becoming_unlocked": unlocked,
        "employees_with_recent_hr_edits_to_newly_locked_fields": recent_hr_edits,
        "events_switched_on": sorted(set(draft.outbound.events) - set(current.outbound.events)),
        "events_switched_off": sorted(set(current.outbound.events) - set(draft.outbound.events)),
        "lifecycle": {
            op: {"from": getattr(current.lifecycle, op), "to": getattr(draft.lifecycle, op)}
            for op in ("hire", "job_change", "exit", "rehire")
            if getattr(current.lifecycle, op) != getattr(draft.lifecycle, op)
        },
        "warnings": profiles.health_warnings(
            draft, company_has_id_scheme=await _has_scheme(session, tenant_id, le)
        ),
    }


@router.post(
    "/profiles/{profile_id}/publish", response_model=ProfileResponse, dependencies=[CONFIGURE]
)
async def publish_profile(
    profile_id: str,
    body: ProfilePublish,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> ProfileResponse:
    pid = to_uuid(profile_id)
    await profiles.publish(session, tenant_id, pid, body.effective_from, principal.user_account_id)
    profile = await profiles.load_profile(session, tenant_id, pid)
    await record_change(
        session,
        tenant_id,
        "integration_profile",
        pid,
        "UPDATE",
        principal.user_account_id,
        {"status": "DRAFT"},
        {
            "status": "PUBLISHED",
            "version": profile["version"],
            "effective_from": body.effective_from,
        },
    )
    return _profile_response(profile)


# ─── Mappings ────────────────────────────────────────────────────────────────

_TARGETS = {
    "LEGAL_ENTITY": ("legal_entities", "name", "legal_entity"),
    "DEPARTMENT": ("org_units", "name", "org_unit"),
    "LOCATION": ("locations", "name", "location"),
    "DESIGNATION": ("jobs", "title", "job"),
}


@router.get(
    "/apps/{app_id}/mappings", response_model=list[MappingResponse], dependencies=[CONFIGURE]
)
async def list_mappings(app_id: str, tenant_id: TenantDep, session: SessionDep):
    app = await _app(session, tenant_id, app_id)
    rows = (
        (
            await session.execute(
                text("""
                SELECT m.*, COALESCE(le.name, ou.name, l.name, j.title) AS target_name
                FROM integration_mappings m
                LEFT JOIN legal_entities le ON m.kind = 'LEGAL_ENTITY'
                     AND le.tenant_id = m.tenant_id AND le.id = m.target_id
                LEFT JOIN org_units ou ON m.kind = 'DEPARTMENT'
                     AND ou.tenant_id = m.tenant_id AND ou.id = m.target_id
                LEFT JOIN locations l ON m.kind = 'LOCATION'
                     AND l.tenant_id = m.tenant_id AND l.id = m.target_id
                LEFT JOIN jobs j ON m.kind = 'DESIGNATION'
                     AND j.tenant_id = m.tenant_id AND j.id = m.target_id
                WHERE m.tenant_id = :tid AND m.app_id = :app
                ORDER BY m.kind, lower(m.external_value)
            """),
                {"tid": tenant_id, "app": app["id"]},
            )
        )
        .mappings()
        .all()
    )
    return [_mapping_response(dict(r)) for r in rows]


def _mapping_response(r: dict[str, Any]) -> MappingResponse:
    kind = r["kind"]
    return MappingResponse(
        id=to_typed_id("integration_mapping", r["id"]),
        kind=kind,
        external_value=r["external_value"],
        target_id=to_typed_id(_TARGETS[kind][2], r["target_id"]) if r["target_id"] else None,
        target_value=r["target_value"],
        target_name=r.get("target_name") or r["target_value"],
        created_at=r["created_at"],
    )


@router.post(
    "/apps/{app_id}/mappings",
    response_model=MappingResponse,
    status_code=201,
    dependencies=[CONFIGURE],
)
async def create_mapping(
    app_id: str,
    body: MappingCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> MappingResponse:
    app = await _app(session, tenant_id, app_id)
    target_id = None
    if body.kind == "ROLE":
        if body.target_value is None:
            raise CodedHTTPException(
                422, "A role maps to EMPLOYEE or MANAGER", code="INVALID_TARGET"
            )
    else:
        if not body.target_id:
            raise CodedHTTPException(422, "target_id is required", code="INVALID_TARGET")
        table = _TARGETS[body.kind][0]
        target_id = to_uuid(body.target_id)
        exists = (
            await session.execute(
                text(f"SELECT 1 FROM {table} WHERE tenant_id = :tid AND id = :id"),
                {"tid": tenant_id, "id": target_id},
            )
        ).first()
        if not exists:
            raise CodedHTTPException(422, "The target doesn't exist", code="INVALID_TARGET")
    dup = (
        await session.execute(
            text("""SELECT 1 FROM integration_mappings WHERE tenant_id = :tid AND app_id = :app
                    AND kind = :kind AND lower(external_value) = lower(:v)"""),
            {"tid": tenant_id, "app": app["id"], "kind": body.kind, "v": body.external_value},
        )
    ).first()
    if dup:
        raise CodedHTTPException(409, "This value is already mapped", code="MAPPING_EXISTS")
    mapping_id = uuid4()
    await session.execute(
        text("""INSERT INTO integration_mappings
                (tenant_id, id, app_id, kind, external_value, target_id, target_value, created_by)
                VALUES (:tid, :id, :app, :kind, :v, :target, :tv, :by)"""),
        {
            "tid": tenant_id,
            "id": mapping_id,
            "app": app["id"],
            "kind": body.kind,
            "v": body.external_value.strip(),
            "target": target_id,
            "tv": body.target_value if body.kind == "ROLE" else None,
            "by": principal.user_account_id,
        },
    )
    await record_change(
        session,
        tenant_id,
        "integration_mapping",
        mapping_id,
        "CREATE",
        principal.user_account_id,
        None,
        {
            "app": app["code"],
            "kind": body.kind,
            "value": body.external_value,
            "target": body.target_id or body.target_value,
        },
    )
    rows = await list_mappings(app_id, tenant_id, session)
    return next(m for m in rows if m.id == to_typed_id("integration_mapping", mapping_id))


@router.delete("/apps/{app_id}/mappings/{mapping_id}", status_code=204, dependencies=[CONFIGURE])
async def delete_mapping(
    app_id: str,
    mapping_id: str,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    app = await _app(session, tenant_id, app_id)
    row = (
        (
            await session.execute(
                text("""DELETE FROM integration_mappings WHERE tenant_id = :tid AND app_id = :app
                        AND id = :id RETURNING kind, external_value"""),
                {"tid": tenant_id, "app": app["id"], "id": to_uuid(mapping_id)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Mapping not found")
    await record_change(
        session,
        tenant_id,
        "integration_mapping",
        to_uuid(mapping_id),
        "ARCHIVE",
        principal.user_account_id,
        {"kind": row["kind"], "value": row["external_value"]},
        None,
    )


@router.get("/apps/{app_id}/unmapped", dependencies=[CONFIGURE])
async def unmapped_values(app_id: str, tenant_id: TenantDep, session: SessionDep):
    """Values the app sent that HRMS couldn't match, not yet mapped (plan §7.3)."""
    app = await _app(session, tenant_id, app_id)
    rows = (
        (
            await session.execute(
                text("""
                SELECT r.error_detail->>'kind' AS kind, r.error_detail->>'value' AS value,
                       count(*) AS requests, max(r.created_at) AS last_seen
                FROM integration_requests r
                WHERE r.tenant_id = :tid AND r.app_id = :app
                  AND r.error_code LIKE 'UNKNOWN_%' AND r.created_at > now() - interval '90 days'
                  AND NOT EXISTS (
                      SELECT 1 FROM integration_mappings m
                      WHERE m.tenant_id = r.tenant_id AND m.app_id = r.app_id
                        AND m.kind = r.error_detail->>'kind'
                        AND lower(m.external_value) = lower(r.error_detail->>'value'))
                GROUP BY 1, 2 ORDER BY max(r.created_at) DESC
            """),
                {"tid": tenant_id, "app": app["id"]},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


# ─── Sync log ────────────────────────────────────────────────────────────────


@router.get("/apps/{app_id}/requests", dependencies=[MANAGE])
async def sync_log(
    app_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    outcome: str | None = None,
    operation: str | None = None,
    external_id: str | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, le=500),
):
    app = await _app(session, tenant_id, app_id)
    where = ["r.tenant_id = :tid", "r.app_id = :app"]
    params: dict[str, Any] = {"tid": tenant_id, "app": app["id"], "limit": limit}
    for column, value in (
        ("outcome", outcome),
        ("operation", operation),
        ("external_id", external_id),
    ):
        if value:
            where.append(f"r.{column} = :{column}")
            params[column] = value
    if before:
        where.append("r.created_at < :before")
        params["before"] = before
    rows = (
        (
            await session.execute(
                text(f"""
                SELECT r.id, r.operation, r.external_id, r.employment_id, r.outcome, r.error_code,
                       r.error_detail, r.changes, r.warnings, r.http_status, r.duration_ms,
                       r.request_id, r.created_at, k.key_prefix,
                       p.legal_first_name || ' ' || p.legal_last_name AS employee_name
                FROM integration_requests r
                LEFT JOIN api_keys k ON k.tenant_id = r.tenant_id AND k.id = r.api_key_id
                LEFT JOIN employments e ON e.tenant_id = r.tenant_id AND e.id = r.employment_id
                LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                WHERE {" AND ".join(where)}
                ORDER BY r.created_at DESC LIMIT :limit
            """),
                params,
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            **{k: v for k, v in r.items() if k not in ("id", "employment_id")},
            "id": to_typed_id("integration_request", r["id"]),
            "employment_id": to_typed_id("employment", r["employment_id"])
            if r["employment_id"]
            else None,
        }
        for r in rows
    ]


# ─── Duplicates, held exits, not linked ──────────────────────────────────────


@router.get("/apps/{app_id}/duplicates", dependencies=[CONFIGURE])
async def list_duplicates(app_id: str, tenant_id: TenantDep, session: SessionDep):
    app = await _app(session, tenant_id, app_id)
    rows = (
        (
            await session.execute(
                text("""
                SELECT d.id, d.external_id, d.employment_id, d.match_reason, d.payload,
                       d.created_at, e.employee_number,
                       p.legal_first_name, p.legal_last_name, p.date_of_birth, ua.email
                FROM possible_duplicates d
                JOIN employments e ON e.tenant_id = d.tenant_id AND e.id = d.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
                WHERE d.tenant_id = :tid AND d.app_id = :app AND d.status = 'OPEN'
                ORDER BY d.created_at DESC
            """),
                {"tid": tenant_id, "app": app["id"]},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": to_typed_id("possible_duplicate", r["id"]),
            "external_id": r["external_id"],
            "match_reason": r["match_reason"],
            "created_at": r["created_at"],
            "app_record": r["payload"],
            "hrms_employee": {
                "employment_id": to_typed_id("employment", r["employment_id"]),
                "employee_code": r["employee_number"],
                "first_name": r["legal_first_name"],
                "last_name": r["legal_last_name"],
                "date_of_birth": r["date_of_birth"],
                "email": r["email"],
            },
        }
        for r in rows
    ]


@router.post("/duplicates/{duplicate_id}/resolve", dependencies=[CONFIGURE])
async def resolve_duplicate(
    duplicate_id: str,
    body: DuplicateResolve,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict[str, Any]:
    from hrms.modules.integrations.service import link_identity

    row = (
        (
            await session.execute(
                text("""SELECT * FROM possible_duplicates WHERE tenant_id = :tid AND id = :id
                        FOR UPDATE"""),
                {"tid": tenant_id, "id": to_uuid(duplicate_id)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Not found")
    if row["status"] != "OPEN":
        raise CodedHTTPException(409, "Already resolved", code="ALREADY_RESOLVED")
    if body.decision == "SAME_PERSON":
        taken = (
            await session.execute(
                text("""SELECT 1 FROM external_identities WHERE tenant_id = :tid AND app_id = :app
                        AND (external_id = :ext OR employment_id = :eid)"""),
                {
                    "tid": tenant_id,
                    "app": row["app_id"],
                    "ext": row["external_id"],
                    "eid": row["employment_id"],
                },
            )
        ).first()
        if taken:
            raise CodedHTTPException(409, "One of the two is already linked", code="ALREADY_LINKED")
        ctx = _admin_context(session, tenant_id, row["app_id"])
        await link_identity(ctx, row["external_id"], row["employment_id"], None)
    await session.execute(
        text("""UPDATE possible_duplicates SET status = :s, resolved_by = :by, resolved_at = now()
                WHERE tenant_id = :tid AND id = :id"""),
        {"s": body.decision, "by": principal.user_account_id, "tid": tenant_id, "id": row["id"]},
    )
    if body.decision == "SAME_PERSON":
        # The record is now linked, so its other candidate matches are settled too.
        await session.execute(
            text("""UPDATE possible_duplicates SET status = 'DIFFERENT_PERSON', resolved_by = :by,
                           resolved_at = now()
                    WHERE tenant_id = :tid AND app_id = :app AND external_id = :ext
                      AND status = 'OPEN'"""),
            {
                "by": principal.user_account_id,
                "tid": tenant_id,
                "app": row["app_id"],
                "ext": row["external_id"],
            },
        )
    return {"status": body.decision}


def _admin_context(session, tenant_id: UUID, app_id: UUID) -> IntegrationContext:
    """Act for an app from an admin screen (linking a confirmed duplicate, releasing an exit)."""
    return IntegrationContext(
        session=session,
        tenant_id=tenant_id,
        app_id=app_id,
        app_code="",
        app_kind="TWO_WAY",
        key_id=uuid4(),
        scopes=frozenset({"employees.sync"}),
        legal_entity_ids=None,
        client_ip="admin",
        request_id=None,
    )


@router.get("/apps/{app_id}/held-exits", dependencies=[CONFIGURE])
async def held_exits(app_id: str, tenant_id: TenantDep, session: SessionDep):
    app = await _app(session, tenant_id, app_id)
    rows = (
        (
            await session.execute(
                text("""
                SELECT r.id, r.external_id, r.employment_id, r.changes, r.created_at,
                       p.legal_first_name || ' ' || p.legal_last_name AS employee_name,
                       e.employee_number
                FROM integration_requests r
                JOIN employments e ON e.tenant_id = r.tenant_id AND e.id = r.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                WHERE r.tenant_id = :tid AND r.app_id = :app AND r.operation = 'EXIT'
                  AND r.outcome = 'HELD_FOR_REVIEW'
                  AND NOT EXISTS (SELECT 1 FROM integration_requests d
                                  WHERE d.tenant_id = r.tenant_id
                                    AND d.operation IN ('EXIT_RELEASED', 'EXIT_REJECTED')
                                    AND d.error_detail->>'held_request_id' = r.id::text)
                ORDER BY r.created_at
            """),
                {"tid": tenant_id, "app": app["id"]},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": to_typed_id("integration_request", r["id"]),
            "external_id": r["external_id"],
            "employment_id": to_typed_id("employment", r["employment_id"]),
            "employee_name": r["employee_name"],
            "employee_code": r["employee_number"],
            "last_working_day": (r["changes"] or {}).get("last_working_day", {}).get("new"),
            "requested_at": r["created_at"],
        }
        for r in rows
    ]


@router.post("/held-exits/{request_id}", dependencies=[CONFIGURE])
async def decide_held_exit(
    request_id: str,
    body: HeldExitDecision,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict[str, Any]:
    from datetime import date

    from hrms.modules.integrations.schemas import ExitRequest
    from hrms.modules.integrations.service import exit_employee, lock_external

    rid = to_uuid(request_id)
    row = (
        (
            await session.execute(
                text("""SELECT * FROM integration_requests WHERE tenant_id = :tid AND id = :id
                        AND operation = 'EXIT' AND outcome = 'HELD_FOR_REVIEW'"""),
                {"tid": tenant_id, "id": rid},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Held exit not found")
    ctx = _admin_context(session, tenant_id, row["app_id"])
    ctx.app_code = (
        await session.execute(
            text("SELECT code FROM connected_apps WHERE tenant_id = :tid AND id = :id"),
            {"tid": tenant_id, "id": row["app_id"]},
        )
    ).scalar_one()
    await lock_external(ctx, row["external_id"])
    decided = (
        await session.execute(
            text("""SELECT 1 FROM integration_requests WHERE tenant_id = :tid
                    AND operation IN ('EXIT_RELEASED', 'EXIT_REJECTED')
                    AND error_detail->>'held_request_id' = :rid"""),
            {"tid": tenant_id, "rid": str(rid)},
        )
    ).first()
    if decided:
        raise CodedHTTPException(409, "Already decided", code="ALREADY_RESOLVED")
    outcome = "REJECTED_BY_HR"
    if body.decision == "RELEASE":
        lwd = date.fromisoformat(row["changes"]["last_working_day"]["new"])
        session.info["integration_origin_app_id"] = row["app_id"]
        result = await exit_employee(
            ctx,
            row["external_id"],
            ExitRequest(
                last_working_day=max(lwd, profiles.business_today()),
                reason_code=(row["changes"] or {}).get("reason_code", {}).get("new")
                if isinstance((row["changes"] or {}).get("reason_code"), dict)
                else None,
            ),
            released=True,
        )
        outcome = result.outcome
    await session.execute(
        text("""
        INSERT INTO integration_requests
            (tenant_id, id, app_id, operation, external_id, employment_id, outcome, error_detail)
        VALUES (:tid, :id, :app, :op, :ext, :eid, :outcome, CAST(:detail AS jsonb))
    """),
        {
            "tid": tenant_id,
            "id": uuid4(),
            "app": row["app_id"],
            "op": "EXIT_RELEASED" if body.decision == "RELEASE" else "EXIT_REJECTED",
            "ext": row["external_id"],
            "eid": row["employment_id"],
            "outcome": outcome,
            "detail": json.dumps(
                {"held_request_id": str(rid), "decided_by": str(principal.user_account_id)}
            ),
        },
    )
    return {"decision": body.decision, "outcome": outcome}


@router.get("/apps/{app_id}/not-linked", dependencies=[CONFIGURE])
async def not_linked(app_id: str, tenant_id: TenantDep, session: SessionDep):
    """Employees hired in HRMS that this app hasn't linked within 24 hours (plan §7.7)."""
    app = await _app(session, tenant_id, app_id)
    rows = (
        (
            await session.execute(
                text("""
                SELECT DISTINCT ON (e.id) e.id, e.employee_number, e.hire_date, ev.occurred_at,
                       p.legal_first_name || ' ' || p.legal_last_name AS employee_name
                FROM integration_events ev
                JOIN integration_app_events ae ON ae.tenant_id = ev.tenant_id
                  AND ae.event_id = ev.id AND ae.app_id = :app
                JOIN employments e ON e.tenant_id = ev.tenant_id AND e.id = ev.employment_id
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                WHERE ev.tenant_id = :tid AND ev.event_type = 'employee.hired'
                  AND ev.origin_app_id IS NULL AND ev.occurred_at < now() - interval '24 hours'
                  AND e.employment_state <> 'SEPARATED'
                  AND NOT EXISTS (SELECT 1 FROM external_identities x
                                  WHERE x.tenant_id = e.tenant_id
                                  AND x.app_id = :app AND x.employment_id = e.id)
                ORDER BY e.id, ev.occurred_at
            """),
                {"tid": tenant_id, "app": app["id"]},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "employment_id": to_typed_id("employment", r["id"]),
            "employee_code": r["employee_number"],
            "employee_name": r["employee_name"],
            "hire_date": r["hire_date"],
            "announced_at": r["occurred_at"],
        }
        for r in rows
    ]


@router.get("/apps/{app_id}/report", dependencies=[MANAGE])
async def app_report(app_id: str, tenant_id: TenantDep, session: SessionDep) -> dict[str, Any]:
    """What does this app receive? (plan §9.4) — for privacy and data-minimisation reviews."""
    app = await _app(session, tenant_id, app_id)
    settings = await profiles.effective_settings(session, tenant_id, app["id"], None)
    keys = await list_keys(app_id, tenant_id, session)
    cursor = (
        (
            await session.execute(
                text(
                    "SELECT position, read_at FROM integration_cursors WHERE tenant_id = :tid "
                    "AND app_id = :app"
                ),
                {"tid": tenant_id, "app": app["id"]},
            )
        )
        .mappings()
        .first()
    )
    reads = (
        await session.execute(
            text("""SELECT count(DISTINCT ev.employment_id) FROM integration_app_events ae
                    JOIN integration_events ev
                      ON ev.tenant_id = ae.tenant_id AND ev.id = ae.event_id
                    WHERE ae.tenant_id = :tid AND ae.app_id = :app AND ae.seq IS NOT NULL
                      AND ae.seq <= COALESCE((SELECT position FROM integration_cursors
                                              WHERE tenant_id = :tid AND app_id = :app), 0)"""),
            {"tid": tenant_id, "app": app["id"]},
        )
    ).scalar_one()
    return {
        "app": {
            "code": app["code"],
            "name": app["name"],
            "kind": app["kind"],
            "status": app["status"],
        },
        "events": settings.outbound.events,
        "data_classes": settings.outbound.data_classes,
        "fields": sorted(events.allowed_fields(settings)),
        "people": {
            "companies": settings.outbound.legal_entity_ids or "all the key allows",
            "departments": settings.outbound.org_unit_ids or "all",
        },
        "scopes_granted": sorted({s for k in keys if k.status == "ACTIVE" for s in k.scopes}),
        "keys": [
            {"name": k.name, "prefix": k.prefix, "status": k.status, "last_used_at": k.last_used_at}
            for k in keys
        ],
        "last_feed_read_at": cursor["read_at"] if cursor else None,
        "employees_delivered_through_feed": reads,
        "linked_employees": (
            await session.execute(
                text(
                    "SELECT count(*) FROM external_identities WHERE tenant_id = :tid "
                    "AND app_id = :app"
                ),
                {"tid": tenant_id, "app": app["id"]},
            )
        ).scalar_one(),
        "never_sent": "KYC identifiers, bank details, salary, passwords",
    }


# ─── Field control on the employee page ──────────────────────────────────────


@employee_router.get("/v1/employees/{employment_id}/field-control")
async def employee_field_control(
    employment_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[dict[str, Any]]:
    """Which of this employee's fields a connected app owns, and whether HR may override them."""
    emp = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, read_scope(scope, "people.read"), emp)
    return await field_control(session, tenant_id, emp)

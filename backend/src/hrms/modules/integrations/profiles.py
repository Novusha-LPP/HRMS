"""
Integration settings with versions (plan §6.1).

A profile is either the tenant default for an app (legal_entity_id NULL, a full settings
document) or one company's override (a partial document laid over the default). Each is
edited as a DRAFT and then PUBLISHED from an effective date; a published version is never
changed, and the version in force is the latest published one whose date has arrived.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.datetime_utils import business_today
from hrms.core.errors import CodedHTTPException
from hrms.modules.integrations.catalog import (
    IntegrationSettings,
    defaults_for,
    merge,
    validate_full,
)


async def _in_force(
    session: AsyncSession, tenant_id: UUID, app_id: UUID, legal_entity_id: UUID | None, on: date
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text("""
                SELECT settings FROM integration_profiles
                WHERE tenant_id = :tid AND app_id = :app
                  AND legal_entity_id IS NOT DISTINCT FROM :le
                  AND status IN ('PUBLISHED', 'SUPERSEDED') AND effective_from <= :on
                ORDER BY effective_from DESC, version DESC
                LIMIT 1
            """),
                {"tid": tenant_id, "app": app_id, "le": legal_entity_id, "on": on},
            )
        )
        .scalars()
        .first()
    )
    return row


async def app_kind(session: AsyncSession, tenant_id: UUID, app_id: UUID) -> str:
    kind = (
        await session.execute(
            text("SELECT kind FROM connected_apps WHERE tenant_id = :tid AND id = :app"),
            {"tid": tenant_id, "app": app_id},
        )
    ).scalar()
    if kind is None:
        raise HTTPException(404, "App not found")
    return kind


async def tenant_settings(
    session: AsyncSession, tenant_id: UUID, app_id: UUID, *, on: date | None = None
) -> dict[str, Any]:
    on = on or business_today()
    base = defaults_for(await app_kind(session, tenant_id, app_id))
    published = await _in_force(session, tenant_id, app_id, None, on)
    return merge(base, published) if published else base


async def effective_settings(
    session: AsyncSession,
    tenant_id: UUID,
    app_id: UUID,
    legal_entity_id: UUID | None,
    *,
    on: date | None = None,
) -> IntegrationSettings:
    """The settings in force for one company (the tenant default plus that company's override)."""
    on = on or business_today()
    settings = await tenant_settings(session, tenant_id, app_id, on=on)
    if legal_entity_id is not None:
        override = await _in_force(session, tenant_id, app_id, legal_entity_id, on)
        if override:
            settings = merge(settings, override)
    return validate_full(settings)


async def app_session_feature_on(
    session: AsyncSession, tenant_id: UUID, key_id: UUID, employment_id: UUID | None, feature: str
) -> bool:
    """Whether the app behind this key switches `feature` on for the employee's company (the
    same test the session gate applies to the feature's routes)."""
    row = (
        await session.execute(
            text("""
                SELECT k.app_id, e.legal_entity_id FROM api_keys k
                LEFT JOIN employments e ON e.tenant_id = k.tenant_id AND e.id = :eid
                WHERE k.tenant_id = :tid AND k.id = :kid
            """),
            {"tid": tenant_id, "kid": key_id, "eid": employment_id},
        )
    ).one_or_none()
    if row is None:
        return False
    options = await effective_settings(session, tenant_id, row.app_id, row.legal_entity_id)
    return bool(getattr(options.self_service, feature))


async def app_marking_entities(session: AsyncSession, tenant_id: UUID, key_id: UUID) -> list[UUID]:
    """
    The companies whose people a session issued through this key may see and mark on the
    marking sheet: those the key covers whose settings switch app marking on. An attendance group
    can span companies, so the marker's own company switching it on isn't enough.
    """
    key = (
        await session.execute(
            text(
                "SELECT app_id, legal_entity_ids FROM api_keys WHERE tenant_id = :tid AND id = :kid"
            ),
            {"tid": tenant_id, "kid": key_id},
        )
    ).one_or_none()
    if key is None:
        return []
    covered = (
        {UUID(str(e)) for e in key.legal_entity_ids} if key.legal_entity_ids is not None else None
    )
    entities = (
        await session.execute(
            text("SELECT id FROM legal_entities WHERE tenant_id = :tid"), {"tid": tenant_id}
        )
    ).scalars()
    return [
        le
        for le in entities
        if (covered is None or le in covered)
        and (await effective_settings(session, tenant_id, key.app_id, le)).self_service.marking
    ]


def check_document(document: dict[str, Any], *, is_override: bool, base: dict[str, Any]) -> None:
    """Refuse a settings document the schema rejects, naming each bad field."""
    try:
        validate_full(merge(base, document) if is_override else merge(base, document))
    except ValidationError as exc:
        raise CodedHTTPException(
            422,
            "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
            )[:900],
            code="INVALID_SETTINGS",
        ) from exc


async def next_version(
    session: AsyncSession, tenant_id: UUID, app_id: UUID, legal_entity_id: UUID | None
) -> int:
    current = (
        await session.execute(
            text("""
            SELECT COALESCE(MAX(version), 0) FROM integration_profiles
            WHERE tenant_id = :tid AND app_id = :app AND legal_entity_id IS NOT DISTINCT FROM :le
        """),
            {"tid": tenant_id, "app": app_id, "le": legal_entity_id},
        )
    ).scalar_one()
    return int(current) + 1


async def create_draft(
    session: AsyncSession,
    tenant_id: UUID,
    app_id: UUID,
    legal_entity_id: UUID | None,
    document: dict[str, Any],
    *,
    created_by: UUID | None,
    note: str | None,
) -> UUID:
    base = await tenant_settings(session, tenant_id, app_id)
    check_document(document, is_override=legal_entity_id is not None, base=base)
    profile_id = uuid4()
    await session.execute(
        text("""
        INSERT INTO integration_profiles
            (tenant_id, id, app_id, legal_entity_id, version, status, settings, note, created_by)
        VALUES (:tid, :id, :app, :le, :version, 'DRAFT', CAST(:settings AS jsonb), :note, :by)
    """),
        {
            "tid": tenant_id,
            "id": profile_id,
            "app": app_id,
            "le": legal_entity_id,
            "version": await next_version(session, tenant_id, app_id, legal_entity_id),
            "settings": json.dumps(document),
            "note": note,
            "by": created_by,
        },
    )
    return profile_id


async def load_profile(session: AsyncSession, tenant_id: UUID, profile_id: UUID) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM integration_profiles WHERE tenant_id = :tid AND id = :id"),
                {"tid": tenant_id, "id": profile_id},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Settings version not found")
    return dict(row)


async def update_draft(
    session: AsyncSession,
    tenant_id: UUID,
    profile_id: UUID,
    document: dict[str, Any],
    note: str | None,
) -> None:
    profile = await load_profile(session, tenant_id, profile_id)
    if profile["status"] != "DRAFT":
        raise CodedHTTPException(
            409, "Only a draft can be edited. Create a new draft instead.", code="NOT_A_DRAFT"
        )
    base = await tenant_settings(session, tenant_id, profile["app_id"])
    check_document(document, is_override=profile["legal_entity_id"] is not None, base=base)
    await session.execute(
        text("""
        UPDATE integration_profiles SET settings = CAST(:settings AS jsonb),
               note = COALESCE(:note, note)
        WHERE tenant_id = :tid AND id = :id
    """),
        {"tid": tenant_id, "id": profile_id, "settings": json.dumps(document), "note": note},
    )


async def publish(
    session: AsyncSession,
    tenant_id: UUID,
    profile_id: UUID,
    effective_from: date,
    published_by: UUID | None,
) -> None:
    profile = await load_profile(session, tenant_id, profile_id)
    if profile["status"] != "DRAFT":
        raise CodedHTTPException(409, "This version is already published", code="NOT_A_DRAFT")
    if effective_from < business_today():
        raise CodedHTTPException(
            422, "Settings can't be published with a date in the past", code="DATE_IN_PAST"
        )
    base = await tenant_settings(session, tenant_id, profile["app_id"], on=effective_from)
    check_document(
        profile["settings"], is_override=profile["legal_entity_id"] is not None, base=base
    )
    # Versions this one replaces from its date stay readable as history.
    await session.execute(
        text("""
        UPDATE integration_profiles SET status = 'SUPERSEDED'
        WHERE tenant_id = :tid AND app_id = :app
          AND legal_entity_id IS NOT DISTINCT FROM :le
          AND status = 'PUBLISHED' AND effective_from <= :d
    """),
        {
            "tid": tenant_id,
            "app": profile["app_id"],
            "le": profile["legal_entity_id"],
            "d": effective_from,
        },
    )
    await session.execute(
        text("""
        UPDATE integration_profiles
        SET status = 'PUBLISHED', effective_from = :d, published_by = :by, published_at = now()
        WHERE tenant_id = :tid AND id = :id
    """),
        {"tid": tenant_id, "id": profile_id, "d": effective_from, "by": published_by},
    )


def health_warnings(settings: IntegrationSettings, *, company_has_id_scheme: bool) -> list[str]:
    """Settings that contradict each other (plan §6.3)."""
    warnings: list[str] = []
    if (
        settings.lifecycle.hire == "HRMS"
        and settings.owner("employee_code") == "APP"
        and not company_has_id_scheme
    ):
        warnings.append(
            "Hiring is allowed only in HRMS, but the app owns the employee code and the company "
            "has no employee ID scheme: HR would have to type a code the app has not issued yet."
        )
    if settings.lifecycle.hire in ("HRMS", "BOTH") and "employee.hired" not in (
        settings.outbound.events
    ):
        warnings.append(
            "Hiring is allowed in HRMS, but the employee.hired event is switched off: the app "
            "will never hear about people hired in HRMS."
        )
    if settings.logins.password_source == "NONE" and not settings.self_service.punch:
        warnings.append(
            "Employees have no direct HRMS sign-in and punching through the app is off: they "
            "have no way to record attendance."
        )
    if settings.owner("employee_code") == "APP" and settings.matching == "NEVER":
        warnings.append(
            "Matching is off: an employee hired in HRMS and later sent by the app is always "
            "queued as a possible duplicate."
        )
    return warnings

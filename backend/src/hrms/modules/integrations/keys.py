"""
Credentials for connected apps, and the request dependency that authenticates them.

A key looks like  hrms_<env>_<prefix>_<secret>  (env = test | live). Only an HMAC of the whole
key is stored; the full key is shown once, when it is created. The same key also works as an
OAuth 2.0 client credential: client_id = "hrms_<env>_<prefix>", client_secret = the key. The
token endpoint swaps it for a 15-minute bearer token.

Keys and integration tokens are accepted only on /v1/integrations/*. No ordinary route reads
X-API-Key, so a leaked key can never reach HR data through the main API.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import string
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core import database
from hrms.core.config import settings
from hrms.core.errors import CodedHTTPException
from hrms.core.logging import get_current_request_id, set_current_tenant_id
from hrms.core.metrics import INTEGRATION_NEW_IP

INTEGRATION_TOKEN_TYPE = "hrms_integration"
INTEGRATION_TOKEN_MINUTES = 15
RATE_SHARDS = 8
_ALPHABET = string.ascii_letters + string.digits

SCOPES: dict[str, str] = {
    "employees.sync": "Create, update, exit and rehire employees",
    "employees.read": "Read employees, reference data and reconciliation",
    "passwords.sync": "Set or change employees' HRMS passwords",
    "sessions.issue": "Get a session token for one employee (self-service through the app)",
    "org.read": "Read companies, departments, locations, designations and holidays",
    "events.read": "Read the events feed",
    "attendance.read": "Read daily attendance",
    "leave.read": "Read approved leave",
}


def key_environment() -> str:
    """Production issues and accepts only live keys; everything else only test keys."""
    return "live" if settings.environment == "production" else "test"


def hash_key(raw: str) -> str:
    return hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """(full key, prefix, client_id). The prefix is public and identifies the key in screens."""
    env = key_environment()
    prefix = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    secret = "".join(secrets.choice(_ALPHABET) for _ in range(40))
    client_id = f"hrms_{env}_{prefix}"
    return f"{client_id}_{secret}", prefix, client_id


def _parse(raw: str) -> tuple[str, str] | None:
    parts = raw.split("_")
    if len(parts) != 4 or parts[0] != "hrms" or parts[1] not in ("test", "live"):
        return None
    return parts[1], parts[2]


@dataclass
class IntegrationContext:
    session: AsyncSession
    tenant_id: UUID
    app_id: UUID
    app_code: str
    app_kind: str
    key_id: UUID
    scopes: frozenset[str]
    legal_entity_ids: frozenset[UUID] | None
    client_ip: str
    request_id: str | None
    info: dict[str, Any] = field(default_factory=dict)

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise CodedHTTPException(
                403, f"This key doesn't have the {scope} scope", code="SCOPE_MISSING"
            )

    def covers_entity(self, legal_entity_id: UUID | None) -> bool:
        return self.legal_entity_ids is None or legal_entity_id in self.legal_entity_ids


def _unauthorized(message: str, code: str) -> CodedHTTPException:
    return CodedHTTPException(401, message, code=code, headers={"WWW-Authenticate": "ApiKey"})


def _ip_allowed(ip: str, allowed: list[str] | None) -> bool:
    if not allowed:
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowed:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _client_ip(request: Request) -> str:
    # Behind a proxy, uvicorn runs with --proxy-headers, so request.client is the real caller.
    return request.client.host if request.client else "unknown"


async def _lookup_by_hash(key_hash: str) -> dict[str, Any] | None:
    async with database.AsyncSessionLocal() as session:
        row = (
            (
                await session.execute(
                    text("SELECT * FROM integration_key_lookup(:h)"), {"h": key_hash}
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def _lookup_by_id(tenant_id: UUID, key_id: UUID) -> dict[str, Any] | None:
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        row = (
            (
                await session.execute(
                    text("""
                    SELECT k.tenant_id, k.id AS key_id, k.app_id, ca.code AS app_code,
                           ca.kind AS app_kind, ca.status AS app_status, k.scopes, k.allowed_ips,
                           k.legal_entity_ids, k.environment, k.is_active, k.expires_at,
                           k.revoked_at, k.rate_limit_per_minute, k.known_ips,
                           t.status AS tenant_status,
                           t.archived_at AS tenant_archived_at
                    FROM api_keys k
                    JOIN connected_apps ca ON ca.tenant_id = k.tenant_id AND ca.id = k.app_id
                    JOIN tenants t ON t.id = k.tenant_id
                    WHERE k.tenant_id = :tid AND k.id = :kid
                """),
                    {"tid": tenant_id, "kid": key_id},
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


def _check_key(row: dict[str, Any] | None, ip: str) -> dict[str, Any]:
    if row is None:
        raise _unauthorized("The API key is not valid", "INVALID_API_KEY")
    if row["environment"] != key_environment():
        raise _unauthorized(
            f"This is a {row['environment']} key; this environment accepts "
            f"{key_environment()} keys",
            "WRONG_ENVIRONMENT",
        )
    if not row["is_active"] or row["revoked_at"] is not None:
        raise _unauthorized("This API key has been revoked", "API_KEY_REVOKED")
    if row["expires_at"] is not None and row["expires_at"] <= datetime.now(UTC):
        raise _unauthorized("This API key has expired", "API_KEY_EXPIRED")
    if row["tenant_status"] != "ACTIVE" or row["tenant_archived_at"] is not None:
        raise CodedHTTPException(
            403, "This company's account is suspended", code="TENANT_SUSPENDED"
        )
    if row["app_status"] == "DISCONNECTED":
        raise _unauthorized("This app has been disconnected", "APP_DISCONNECTED")
    if row["app_status"] == "PAUSED":
        raise CodedHTTPException(403, "This app is paused", code="APP_PAUSED")
    if not _ip_allowed(ip, row["allowed_ips"]):
        raise CodedHTTPException(
            403, "Requests from this address are not allowed for this key", code="IP_NOT_ALLOWED"
        )
    return row


async def _count_request(row: dict[str, Any], ip: str) -> None:
    """Rate limit and usage, in their own committed transaction (a refused request still counts)."""
    window = datetime.now(UTC).replace(second=0, microsecond=0)
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(row["tenant_id"])}
        )
        # The minute's count is spread over RATE_SHARDS rows, and the key's "last used" is
        # refreshed at most every 15 seconds (or when the address changes): otherwise every
        # call with one key would wait for the previous call's lock on the same row.
        await session.execute(
            text("""
            INSERT INTO integration_rate_windows
                (tenant_id, api_key_id, window_start, shard, count)
            VALUES (:tid, :kid, :w, :shard, 1)
            ON CONFLICT (tenant_id, api_key_id, window_start, shard)
            DO UPDATE SET count = integration_rate_windows.count + 1
        """),
            {
                "tid": row["tenant_id"],
                "kid": row["key_id"],
                "w": window,
                "shard": secrets.randbelow(RATE_SHARDS),
            },
        )
        count = (
            await session.execute(
                text("""
                SELECT COALESCE(sum(count), 0) FROM integration_rate_windows
                WHERE tenant_id = :tid AND api_key_id = :kid AND window_start = :w
            """),
                {"tid": row["tenant_id"], "kid": row["key_id"], "w": window},
            )
        ).scalar_one()
        await session.execute(
            text("""
            UPDATE api_keys SET last_used_at = now(), last_used_ip = :ip
            WHERE tenant_id = :tid AND id = :kid
              AND (last_used_at IS NULL OR last_used_at < now() - interval '15 seconds'
                   OR last_used_ip IS DISTINCT FROM :ip)
        """),
            {"tid": row["tenant_id"], "kid": row["key_id"], "ip": ip[:45]},
        )
        known = list(row.get("known_ips") or [])
        if ip not in known:
            # Remember the address; the first use from a new one after the key's first use is
            # worth a look (alert HrmsApiKeyNewAddress), so it goes in the sync log too.
            await session.execute(
                text("""
                UPDATE api_keys SET known_ips = CAST(:ips AS jsonb)
                WHERE tenant_id = :tid AND id = :kid
            """),
                {
                    "tid": row["tenant_id"],
                    "kid": row["key_id"],
                    "ips": json.dumps((known + [ip])[-50:]),
                },
            )
            if known:
                await session.execute(
                    text("""
                    INSERT INTO integration_requests
                        (tenant_id, id, app_id, api_key_id, operation, outcome, error_detail)
                    VALUES (:tid, gen_random_uuid(), :app, :kid, 'NEW_IP', 'NOTICED',
                            CAST(:detail AS jsonb))
                """),
                    {
                        "tid": row["tenant_id"],
                        "app": row["app_id"],
                        "kid": row["key_id"],
                        "detail": json.dumps({"ip": ip, "known": known[-5:]}),
                    },
                )
                INTEGRATION_NEW_IP.labels(row["app_code"]).inc()
        if secrets.randbelow(100) == 0:  # housekeeping without a scheduler
            await session.execute(
                text(
                    "DELETE FROM integration_rate_windows "
                    "WHERE tenant_id = :tid AND window_start < now() - interval '1 hour'"
                ),
                {"tid": row["tenant_id"]},
            )
        await session.commit()
    if count > row["rate_limit_per_minute"]:
        retry = 60 - datetime.now(UTC).second
        raise CodedHTTPException(
            429,
            "Too many requests for this key. Wait and retry.",
            code="RATE_LIMITED",
            headers={"Retry-After": str(max(retry, 1))},
        )


async def authenticate(request: Request) -> dict[str, Any]:
    """Resolve the credential on this request to a checked key row."""
    ip = _client_ip(request)
    raw = request.headers.get("x-api-key", "").strip()
    if raw:
        if _parse(raw) is None:
            raise _unauthorized("The API key is not valid", "INVALID_API_KEY")
        row = _check_key(await _lookup_by_hash(hash_key(raw)), ip)
    else:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise _unauthorized(
                "Send an API key in X-API-Key, or an integration token as a Bearer token",
                "API_KEY_REQUIRED",
            )
        try:
            claims = jwt.decode(
                auth[7:].strip(), settings.secret_key, algorithms=[settings.algorithm]
            )
            if claims.get("typ") != INTEGRATION_TOKEN_TYPE:
                raise jwt.InvalidTokenError("wrong token type")
            tenant_id, key_id = UUID(claims["tid"]), UUID(claims["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise _unauthorized("Invalid or expired integration token", "INVALID_TOKEN") from exc
        row = _check_key(await _lookup_by_id(tenant_id, key_id), ip)
    await _count_request(row, ip)
    return row


async def get_integration_context(request: Request) -> AsyncGenerator[IntegrationContext, None]:
    row = await authenticate(request)
    tenant_id = row["tenant_id"]
    set_current_tenant_id(str(tenant_id))
    entity_ids = row["legal_entity_ids"]
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        ctx = IntegrationContext(
            session=session,
            tenant_id=tenant_id,
            app_id=row["app_id"],
            app_code=row["app_code"],
            app_kind=row["app_kind"],
            key_id=row["key_id"],
            scopes=frozenset(row["scopes"] or []),
            legal_entity_ids=(
                frozenset(UUID(str(e)) for e in entity_ids) if entity_ids is not None else None
            ),
            client_ip=_client_ip(request),
            request_id=get_current_request_id(),
        )
        request.state.integration = ctx
        try:
            yield ctx
            await session.commit()
        except Exception:
            await session.rollback()
            raise


IntegrationDep = Annotated[IntegrationContext, Depends(get_integration_context, scope="function")]


# ─── OAuth 2.0 client credentials ────────────────────────────────────────────


async def issue_client_token(client_id: str, client_secret: str, ip: str) -> dict[str, Any]:
    parsed = _parse(client_secret)
    if parsed is None or not client_secret.startswith(client_id + "_"):
        raise CodedHTTPException(401, "Invalid client credentials", code="invalid_client")
    try:
        row = _check_key(await _lookup_by_hash(hash_key(client_secret)), ip)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise CodedHTTPException(
                401, "Invalid client credentials", code="invalid_client"
            ) from exc
        raise
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "typ": INTEGRATION_TOKEN_TYPE,
            "sub": str(row["key_id"]),
            "tid": str(row["tenant_id"]),
            "iat": int(now.timestamp()),
            "exp": now + timedelta(minutes=INTEGRATION_TOKEN_MINUTES),
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": INTEGRATION_TOKEN_MINUTES * 60,
        "scope": " ".join(sorted(row["scopes"] or [])),
    }

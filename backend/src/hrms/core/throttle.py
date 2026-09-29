"""
Brute-force protection for unauthenticated endpoints.

Counters live in the auth_throttle table (migration 0019) rather than in
process memory, so they hold across API workers and restarts. Keys are stored
only as SHA-256 hashes — the table never contains an identifier or an IP.

Every function here opens its OWN short session and commits immediately. That
is deliberate: the login handler ends by raising 401, which rolls back the
request's session — a failure counter written on that session would be rolled
back with it and never count.
"""

import hashlib
import logging
import random

from fastapi import HTTPException, Request, status
from sqlalchemy import text

from hrms.core import database
from hrms.core.config import settings

logger = logging.getLogger(__name__)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_identifier(identifier: str) -> str:
    return identifier.strip().lower()


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, run uvicorn with --proxy-headers (and
    # --forwarded-allow-ips) so request.client is the real caller, not the proxy.
    return request.client.host if request.client else "unknown"


async def ensure_not_locked(scope: str, key: str) -> None:
    """Raise 429 (with Retry-After) if this key is currently locked out."""
    if not settings.throttle_enabled:
        return
    async with database.AsyncSessionLocal() as session:
        wait = (
            await session.execute(
                text("""
                    SELECT CEIL(EXTRACT(EPOCH FROM (locked_until - now())))::int
                    FROM auth_throttle
                    WHERE scope = :scope AND key_hash = :key AND locked_until > now()
                """),
                {"scope": scope, "key": _hash(key)},
            )
        ).scalar()
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please wait a few minutes and try again.",
            headers={"Retry-After": str(max(int(wait), 1))},
        )


async def record_attempt(
    scope: str, key: str, *, max_attempts: int, window_minutes: int, lock_minutes: int
) -> None:
    """
    Count one attempt against this key. Once max_attempts land inside the
    window the key is locked for lock_minutes. The window restarts on the first
    attempt after it expires, so a lockout that equals the window always clears.
    """
    if not settings.throttle_enabled:
        return
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO auth_throttle (scope, key_hash, failures, window_started_at)
                VALUES (:scope, :key, 1, now())
                ON CONFLICT (scope, key_hash) DO UPDATE SET
                    failures = CASE
                        WHEN auth_throttle.window_started_at
                             < now() - make_interval(mins => :window)
                        THEN 1 ELSE auth_throttle.failures + 1 END,
                    window_started_at = CASE
                        WHEN auth_throttle.window_started_at
                             < now() - make_interval(mins => :window)
                        THEN now() ELSE auth_throttle.window_started_at END,
                    locked_until = CASE
                        WHEN (CASE
                                WHEN auth_throttle.window_started_at
                                     < now() - make_interval(mins => :window)
                                THEN 1 ELSE auth_throttle.failures + 1 END) >= :max
                        THEN now() + make_interval(mins => :lock)
                        ELSE NULL END
            """),
            {
                "scope": scope,
                "key": _hash(key),
                "window": window_minutes,
                "max": max_attempts,
                "lock": lock_minutes,
            },
        )
        if random.random() < 0.01:  # cheap housekeeping, no scheduler needed
            await session.execute(
                text("""
                    DELETE FROM auth_throttle
                    WHERE window_started_at < now() - interval '1 day'
                      AND (locked_until IS NULL OR locked_until < now())
                """)
            )
        await session.commit()


async def clear(scope: str, key: str) -> None:
    """Forget a key's failures (called after a successful sign-in)."""
    if not settings.throttle_enabled:
        return
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM auth_throttle WHERE scope = :scope AND key_hash = :key"),
            {"scope": scope, "key": _hash(key)},
        )
        await session.commit()


# ─── Login ───────────────────────────────────────────────────────────────────
#
# `realm` keeps counters for different sign-in surfaces apart (tenant users vs
# the platform console), so hammering one can't lock the other.


def _login_keys(identifier: str, ip: str, realm: str) -> list[tuple[str, str, int]]:
    ident = normalize_identifier(identifier)
    return [
        (f"{realm}:id+ip", f"{ident}|{ip}", settings.login_max_failures),
        (f"{realm}:id", ident, settings.login_identifier_max_failures),
        (f"{realm}:ip", ip, settings.login_ip_max_failures),
    ]


async def check_login_allowed(identifier: str, ip: str, realm: str = "login") -> None:
    for scope, key, _ in _login_keys(identifier, ip, realm):
        await ensure_not_locked(scope, key)


async def record_login_failure(identifier: str, ip: str, realm: str = "login") -> None:
    for scope, key, limit in _login_keys(identifier, ip, realm):
        await record_attempt(
            scope,
            key,
            max_attempts=limit,
            window_minutes=settings.login_lockout_minutes,
            lock_minutes=settings.login_lockout_minutes,
        )


async def record_login_success(identifier: str, ip: str, realm: str = "login") -> None:
    # Only the identifier-specific counters reset; the IP counter keeps
    # counting so one address can't launder failures with an occasional success.
    for scope, key, _ in _login_keys(identifier, ip, realm)[:2]:
        await clear(scope, key)


# ─── Plain rate limits (anonymous endpoints that aren't sign-in) ─────────────


async def rate_limit(scope: str, key: str, *, max_per_hour: int) -> None:
    """Refuse (429) once `key` has hit this scope more than max_per_hour times in an hour."""
    await ensure_not_locked(scope, key)
    await record_attempt(scope, key, max_attempts=max_per_hour, window_minutes=60, lock_minutes=60)


async def check_registration_allowed(ip: str) -> None:
    await ensure_not_locked("register:ip", ip)


async def record_registration(ip: str) -> None:
    await record_attempt(
        "register:ip",
        ip,
        max_attempts=settings.register_max_per_hour,
        window_minutes=60,
        lock_minutes=60,
    )

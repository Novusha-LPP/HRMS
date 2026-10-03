"""
Password hashing and JWT issuance/verification.

The access token is the only source of truth for who a request is and what
tenant it belongs to — nothing downstream trusts a client-supplied tenant or
employment id. See core/authn.py for how the token is turned into a Principal.
"""

import asyncio
import functools
import hashlib
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
import jwt
from jwt import PyJWTError

from hrms.core.config import settings

TOKEN_TYPE = "hrms_access"
# Deliberately different from TOKEN_TYPE so a platform token can never be
# accepted where a tenant token is expected, or vice versa — there is no
# tenant_id claim on this one at all, by design (see kernel/models.PlatformAdmin).
PLATFORM_TOKEN_TYPE = "hrms_platform"
_BCRYPT_MAX_BYTES = 72  # bcrypt silently ignores anything past this; reject instead

# bcrypt is deliberately slow (~170 ms) and CPU-bound. Calling it directly in
# an `async def` freezes the whole event loop — every other request on the
# worker — for that long, so async code must go through ahash_password /
# averify_password below. A small dedicated pool also bounds how much CPU a
# burst of logins can take from the rest of the API.
_PASSWORD_POOL = ThreadPoolExecutor(
    max_workers=max(2, min(4, os.cpu_count() or 2)), thread_name_prefix="bcrypt"
)


class TokenError(Exception):
    """Raised for any invalid, expired or malformed access token."""


class PasswordTooLong(ValueError):
    """The password is longer than bcrypt's 72-byte limit (counted in UTF-8 bytes)."""


def password_fits_bcrypt(plain: str) -> bool:
    """Schemas count characters; bcrypt counts bytes — a 30-emoji password is 120 bytes."""
    return len(plain.encode("utf-8")) <= _BCRYPT_MAX_BYTES


def hash_password(plain: str) -> str:
    raw = plain.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise PasswordTooLong(f"Password must be at most {_BCRYPT_MAX_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    raw = plain.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, hashed.encode("ascii"))
    except ValueError:
        return False


async def ahash_password(plain: str) -> str:
    """hash_password without blocking the event loop."""
    return await asyncio.get_running_loop().run_in_executor(_PASSWORD_POOL, hash_password, plain)


async def averify_password(plain: str, hashed: str | None) -> bool:
    """verify_password without blocking the event loop."""
    if not hashed:
        return False
    return await asyncio.get_running_loop().run_in_executor(
        _PASSWORD_POOL, verify_password, plain, hashed
    )


@functools.cache
def _dummy_hash() -> str:
    return bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode("ascii")


async def spend_verification_time(plain: str) -> None:
    """
    Burn the same time a real password check takes. Login calls this when the
    identifier matched no usable account, so "no such account" and "wrong
    password" cost the same and can't be told apart by timing.
    """
    await averify_password(plain, _dummy_hash())


def create_access_token(
    *,
    user_account_id: UUID,
    tenant_id: UUID,
    employment_id: UUID | None,
    role_names: list[str],
    expires_minutes: int | None = None,
    token_epoch: int = 0,
) -> str:
    now = datetime.now(UTC)
    expires_minutes = expires_minutes or settings.access_token_expire_minutes
    claims: dict[str, Any] = {
        "typ": TOKEN_TYPE,
        "sub": str(user_account_id),
        "tenant_id": str(tenant_id),
        "employment_id": str(employment_id) if employment_id else None,
        "roles": role_names,
        "ep": token_epoch,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims.get("typ") != TOKEN_TYPE:
        raise TokenError("Wrong token type")
    return claims


def create_platform_token(*, admin_id: UUID, expires_minutes: int | None = None) -> str:
    now = datetime.now(UTC)
    expires_minutes = expires_minutes or settings.access_token_expire_minutes
    claims: dict[str, Any] = {
        "typ": PLATFORM_TOKEN_TYPE,
        "sub": str(admin_id),
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)


def decode_platform_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims.get("typ") != PLATFORM_TOKEN_TYPE:
        raise TokenError("Wrong token type")
    return claims


def generate_reset_token() -> str:
    """High-entropy, single-use, sent to the user once and never stored raw."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    # sha256, not bcrypt: this is a random 256-bit token, not a user-chosen
    # password, so there's no offline-guessing risk to slow down — a fast
    # hash is the right tool for "does this exact token match".
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

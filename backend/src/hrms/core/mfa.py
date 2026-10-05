"""RFC 6238 authenticator enrollment and replay-protected verification."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from hrms.core import throttle
from hrms.core.errors import CodedHTTPException
from hrms.core.field_crypto import cipher
from hrms.core.security import averify_password

PRIVILEGED_ROLES = {"SUPER_ADMIN", "HR_MANAGER", "ACCOUNTANT"}
EXEMPT_PATHS = {
    "/v1/auth/me",
    "/v1/auth/change-password",
    "/v1/auth/logout",
    "/v1/auth/mfa/enroll",
    "/v1/auth/mfa/confirm",
    "/v1/platform/me",
    "/v1/platform/logout",
    "/v1/platform/mfa/enroll",
    "/v1/platform/mfa/confirm",
}


class EnrollRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ConfirmRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


def totp(secret: str, step: int, *, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def matching_step(secret: str, code: str | None, last_step: int = -1, *, now: float | None = None):
    if code is None or len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current = int((time.time() if now is None else now) // 30)
    for step in (current, current - 1, current + 1):
        if step >= 0 and step > last_step and hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def account_sql(platform, tenant_id, account_id):
    # Identifiers are fixed constants, never client input.
    return (
        "platform_admins" if platform else "user_accounts",
        "id=:uid" if platform else "tenant_id=:tid AND id=:uid",
        {"uid": account_id} if platform else {"uid": account_id, "tid": tenant_id},
    )


async def verify_login(session, account, code, *, platform=False, tenant_id=None):
    stored = account["mfa_secret"]
    if not stored:
        return False
    if not code:
        raise CodedHTTPException(401, "Enter your authenticator code", code="MFA_REQUIRED")
    secret = cipher().decrypt(stored, "mfa_secret")
    step = matching_step(secret, code, account["mfa_last_step"])
    if step is None:
        raise CodedHTTPException(
            401, "Invalid or already used authenticator code", code="MFA_INVALID"
        )
    table, where, params = account_sql(platform, tenant_id, account["id"])
    updated = (
        await session.execute(
            text(
                f"UPDATE {table} SET mfa_last_step=:step "
                f"WHERE {where} AND mfa_last_step<:step AND mfa_secret=:secret "
                "AND token_epoch=:epoch AND status='ACTIVE' RETURNING id"
            ),
            {**params, "step": step, "secret": stored, "epoch": account["token_epoch"]},
        )
    ).scalar()
    if updated is None:
        raise CodedHTTPException(
            401, "Invalid or already used authenticator code", code="MFA_INVALID"
        )
    return True


async def enroll(session, account_id, password, *, platform=False, tenant_id=None):
    key = f"{platform}:{tenant_id}:{account_id}"
    await throttle.ensure_not_locked("mfa-enroll", key)
    table, where, params = account_sql(platform, tenant_id, account_id)
    account = (
        (
            await session.execute(
                text(f"SELECT password_hash,mfa_secret FROM {table} WHERE {where} FOR UPDATE"),
                params,
            )
        )
        .mappings()
        .one()
    )
    if not await averify_password(password, account["password_hash"]):
        await throttle.record_attempt(
            "mfa-enroll", key, max_attempts=5, window_minutes=15, lock_minutes=15
        )
        raise HTTPException(400, "Incorrect current password")
    if account["mfa_secret"]:
        raise HTTPException(409, "Authenticator already enrolled; use the recovery procedure")
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    await session.execute(
        text(f"UPDATE {table} SET mfa_pending_secret=:secret,mfa_pending_at=:now WHERE {where}"),
        {**params, "secret": cipher().encrypt(secret, "mfa_secret"), "now": datetime.now(UTC)},
    )
    await throttle.clear("mfa-enroll", key)
    label = quote(f"HRMS:{account_id}", safe="")
    return {
        "secret": secret,
        "uri": f"otpauth://totp/{label}?secret={secret}&issuer=HRMS&digits=6&period=30",
    }


async def confirm(session, account_id, code, *, platform=False, tenant_id=None):
    key = f"{platform}:{tenant_id}:{account_id}"
    await throttle.ensure_not_locked("mfa-confirm", key)
    table, where, params = account_sql(platform, tenant_id, account_id)
    row = (
        (
            await session.execute(
                text(
                    f"SELECT mfa_pending_secret,mfa_pending_at,mfa_secret "
                    f"FROM {table} WHERE {where} FOR UPDATE"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    if (
        row["mfa_secret"]
        or not row["mfa_pending_secret"]
        or row["mfa_pending_at"] < datetime.now(UTC) - timedelta(minutes=10)
    ):
        raise HTTPException(409, "Enrollment expired or already completed; start again")
    step = matching_step(cipher().decrypt(row["mfa_pending_secret"], "mfa_secret"), code)
    if step is None:
        await throttle.record_attempt(
            "mfa-confirm", key, max_attempts=5, window_minutes=15, lock_minutes=15
        )
        raise HTTPException(400, "Invalid authenticator code")
    await session.execute(
        text(
            f"UPDATE {table} SET mfa_secret=mfa_pending_secret, mfa_pending_secret=NULL, "
            f"mfa_pending_at=NULL,mfa_last_step=:step,token_epoch=token_epoch+1 WHERE {where}"
        ),
        {**params, "step": step},
    )
    await throttle.clear("mfa-confirm", key)

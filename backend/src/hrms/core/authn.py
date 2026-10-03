"""
Request identity — who is calling, derived only from a verified JWT.

Every other module (tenancy, authz, and every router) must treat this as the
single source of truth for "who is this" and "which tenant". Nothing reads
identity from a header or query parameter the client controls.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from hrms.core.logging import set_current_tenant_id, set_current_user_id
from hrms.core.security import TokenError, decode_access_token, decode_platform_token


@dataclass(frozen=True)
class Principal:
    tenant_id: UUID
    user_account_id: UUID
    employment_id: UUID | None
    role_names: frozenset[str]
    # The account's token epoch when this token was issued (claim "ep"; absent
    # on tokens from before it existed = 0). A password change or reset bumps
    # the account's epoch, ending every session — see core/database.get_session.
    token_epoch: int = 0


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_principal(request: Request) -> Principal:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise _unauthorized("Missing bearer token")

    token = auth_header[len("Bearer ") :].strip()
    if not token:
        raise _unauthorized("Missing bearer token")

    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    try:
        tenant_id = UUID(claims["tenant_id"])
        user_account_id = UUID(claims["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise _unauthorized("Malformed token") from exc

    try:
        employment_raw = claims.get("employment_id")
        employment_id = UUID(employment_raw) if employment_raw else None
        token_epoch = int(claims.get("ep") or 0)
    except (ValueError, TypeError) as exc:
        raise _unauthorized("Malformed token") from exc

    principal = Principal(
        tenant_id=tenant_id,
        user_account_id=user_account_id,
        employment_id=employment_id,
        role_names=frozenset(claims.get("roles") or []),
        token_epoch=token_epoch,
    )
    request.state.principal = principal
    request.state.tenant_id = tenant_id
    set_current_tenant_id(str(tenant_id))
    set_current_user_id(str(user_account_id))
    return principal


CurrentUser = Annotated[Principal, Depends(get_current_principal)]


@dataclass(frozen=True)
class PlatformPrincipal:
    admin_id: UUID
    token_epoch: int = 0


async def get_current_platform_principal(request: Request) -> PlatformPrincipal:
    """
    Deliberately does not reuse get_current_principal — a platform token has
    no tenant_id claim at all, so decode_access_token would just KeyError on
    it. Kept as a fully separate check so a tenant token can never satisfy a
    platform-only route (wrong `typ`, rejected outright) and a platform token
    can never satisfy a tenant-scoped route the same way.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise _unauthorized("Missing bearer token")

    token = auth_header[len("Bearer ") :].strip()
    if not token:
        raise _unauthorized("Missing bearer token")

    try:
        claims = decode_platform_token(token)
    except TokenError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    try:
        admin_id = UUID(claims["sub"])
        token_epoch = int(claims.get("ep") or 0)
    except (KeyError, ValueError, TypeError) as exc:
        raise _unauthorized("Malformed token") from exc

    set_current_user_id(str(admin_id))
    return PlatformPrincipal(admin_id=admin_id, token_epoch=token_epoch)


CurrentPlatformAdmin = Annotated[PlatformPrincipal, Depends(get_current_platform_principal)]

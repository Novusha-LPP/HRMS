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

from hrms.core.browser_sessions import token_from_request
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
    mfa_verified: bool = False
    # Set when a connected app obtained this token for the employee (POST
    # /v1/integrations/sessions): the issuing API key and the app's code. Such a token is
    # limited to self-service routes and EMPLOYEE/MANAGER rights (core/database.get_session).
    via_key_id: UUID | None = None
    via_app: str | None = None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_principal(request: Request) -> Principal:
    token = token_from_request(request)
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
        via_key_id = UUID(claims["via"]) if claims.get("via") else None
    except (ValueError, TypeError) as exc:
        raise _unauthorized("Malformed token") from exc

    principal = Principal(
        tenant_id=tenant_id,
        user_account_id=user_account_id,
        employment_id=employment_id,
        role_names=frozenset(claims.get("roles") or []),
        token_epoch=token_epoch,
        mfa_verified=claims.get("mfa") is True,
        via_key_id=via_key_id,
        via_app=str(claims["ext"]) if via_key_id and claims.get("ext") else None,
    )
    if via_key_id is not None:
        # Defence in depth: get_session also checks this (with the app's live settings), but a
        # route that never opens a session must not be reachable with an app-issued token.
        from hrms.modules.integrations.session_policy import route_features

        if not route_features(request.method, request.url.path)[0]:
            from hrms.core.errors import CodedHTTPException

            raise CodedHTTPException(
                403,
                "This isn't available through a connected app. Sign in to HRMS to use it.",
                code="NOT_AVAILABLE_VIA_INTEGRATION",
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
    mfa_verified: bool = False


async def get_current_platform_principal(request: Request) -> PlatformPrincipal:
    """
    Deliberately does not reuse get_current_principal — a platform token has
    no tenant_id claim at all, so decode_access_token would just KeyError on
    it. Kept as a fully separate check so a tenant token can never satisfy a
    platform-only route (wrong `typ`, rejected outright) and a platform token
    can never satisfy a tenant-scoped route the same way.
    """
    token = token_from_request(request, platform=True)
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
    return PlatformPrincipal(admin_id=admin_id, token_epoch=token_epoch,
                             mfa_verified=claims.get("mfa") is True)


CurrentPlatformAdmin = Annotated[PlatformPrincipal, Depends(get_current_platform_principal)]

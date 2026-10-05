"""
Platform admin authorization — resolved fresh from the database on every
request, never baked into the JWT.

core.authn.get_current_platform_principal only decodes the token (admin_id).
Role and status are deliberately NOT JWT claims: if they were, demoting an
ADMIN to VIEWER — or suspending them — wouldn't take effect until their
token naturally expired (up to 8 hours). Checking live here means a
suspended or demoted platform admin is rejected on their very next request,
the same real-time-enforcement principle used for tenant suspension in
modules/kernel/auth/router.login().

This lives in its own module (not core/authn.py) to avoid a circular import:
core/database.py -> core/tenancy.py -> core/authn.py, so authn.py can't
import database.py's AnonymousSessionDep without a cycle.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text

from hrms.core.authn import CurrentPlatformAdmin
from hrms.core.config import settings
from hrms.core.database import AnonymousSessionDep
from hrms.core.errors import CodedHTTPException
from hrms.core.mfa import EXEMPT_PATHS


@dataclass(frozen=True)
class PlatformAdminContext:
    admin_id: UUID
    name: str
    email: str
    role: str  # ADMIN | VIEWER
    mfa_required: bool = False


async def get_platform_admin_context(
    principal: CurrentPlatformAdmin,
    request: Request,
    session: AnonymousSessionDep,
) -> PlatformAdminContext:
    row = (
        (
            await session.execute(
                text(
                    "SELECT name, email, role, status, token_epoch, mfa_secret "
                    "FROM platform_admins WHERE id = :id"
                ),
                {"id": str(principal.admin_id)},
            )
        )
        .mappings()
        .first()
    )
    if not row or row["status"] != "ACTIVE" or row["token_epoch"] != principal.token_epoch:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "This account is no longer active",
            headers={"WWW-Authenticate": "Bearer"},
        )
    required = settings.privileged_mfa_required or bool(row["mfa_secret"])
    if required and not principal.mfa_verified and request.url.path not in EXEMPT_PATHS:
        raise CodedHTTPException(
            403, "Set up your authenticator and sign in again", code="MFA_SETUP_REQUIRED"
        )
    return PlatformAdminContext(
        admin_id=principal.admin_id,
        name=row["name"],
        email=row["email"],
        role=row["role"],
        mfa_required=required and not principal.mfa_verified,
    )


CurrentPlatformAdminCtx = Annotated[PlatformAdminContext, Depends(get_platform_admin_context)]


def require_platform_role(*roles: str):
    async def _dep(ctx: CurrentPlatformAdminCtx) -> PlatformAdminContext:
        if ctx.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You have read-only access — ask an admin to make this change",
            )
        return ctx

    return Depends(_dep)

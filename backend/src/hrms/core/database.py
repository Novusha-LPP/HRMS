"""
Async SQLAlchemy engine + session factory with per-transaction tenant isolation.

Every session runs SET LOCAL app.tenant_id = '<uuid>' before any statement so
PostgreSQL row-level security policies can read the tenant from current_setting().
This is a real second layer, not just decoration: the engine connects as
hrms_app (see migration 0005), a role with NOSUPERUSER and NOBYPASSRLS, so a
bug that forgets a WHERE tenant_id = ... clause still can't read another
tenant's rows — Postgres itself refuses.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from hrms.core.authn import CurrentUser
from hrms.core.config import settings
from hrms.core.errors import CodedHTTPException
from hrms.core.tenancy import TenantDep

logger = logging.getLogger(__name__)

# A user who must change their password (freshly imported, or reset by an
# admin) may only reach these until they have. Everything else is refused
# server-side — the frontend redirect is a convenience, not the control.
PASSWORD_CHANGE_EXEMPT_PATHS = frozenset({"/v1/auth/change-password", "/v1/auth/me"})

engine = create_async_engine(
    settings.app_database_url or settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.debug,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session(
    request: Request, tenant_id: TenantDep, principal: CurrentUser
) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a session with the tenant context already set in PostgreSQL.
    This makes RLS policies active for the life of the session.

    Declaring `tenant_id: TenantDep` here (rather than reading a ContextVar
    a sibling dependency happens to have set) means this is correct no
    matter what else a route declares or which order it declares them in —
    FastAPI resolves this function's own sub-dependencies for us.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        # Suspension/archival is checked here too, not just at login — a
        # platform admin suspending a tenant mid-session should cut off its
        # already-issued tokens on their very next request, not wait out an
        # up-to-8h JWT. tenants has no RLS, so this SELECT is unaffected by
        # the set_config just above.
        row = (
            (
                await session.execute(
                    text("SELECT status, archived_at FROM tenants WHERE id = :tid"),
                    {"tid": str(tenant_id)},
                )
            )
            .mappings()
            .first()
        )
        if not row or row["status"] != "ACTIVE" or row["archived_at"] is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This company's account is suspended")
        # One query answers every "may this token still act?" question. The
        # employment's state is read live, so a separation locks the person out
        # from the moment it's applied and a rehire lets them back in, with no
        # account flag to keep in sync.
        account = (
            (
                await session.execute(
                    text("""
            SELECT ua.status, ua.employment_id, ua.must_change_password,
                   ua.token_epoch, e.employment_state
            FROM user_accounts ua
            LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
            WHERE ua.tenant_id = :tid AND ua.id = :uid
        """),
                    {"tid": tenant_id, "uid": principal.user_account_id},
                )
            )
            .mappings()
            .first()
        )
        if (
            not account
            or account["status"] != "ACTIVE"
            or account["employment_id"] != principal.employment_id
            or account["employment_state"] == "SEPARATED"
        ):
            raise HTTPException(401, "This account is no longer active; sign in again")
        if account["token_epoch"] != principal.token_epoch:
            raise HTTPException(401, "Your password was changed; sign in again")
        if account["must_change_password"] and request.url.path not in PASSWORD_CHANGE_EXEMPT_PATHS:
            raise CodedHTTPException(
                status.HTTP_403_FORBIDDEN,
                "You must change your password before continuing",
                code="PASSWORD_CHANGE_REQUIRED",
            )
        try:
            await _apply_scheduled_actions(session, tenant_id)
            yield session
            await session.commit()
            _finish_files(session, committed=True)
        except Exception:
            await session.rollback()
            _finish_files(session, committed=False)
            raise


async def _apply_scheduled_actions(session: AsyncSession, tenant_id) -> None:
    """
    Apply personnel actions whose effective date has arrived. Runs on every
    authenticated request, so it must never be able to take the API down:
    apply_due_actions isolates each action in its own savepoint and parks a
    failing one as FAILED. Worst case a scheduled change is applied a request
    later — never a tenant-wide outage. (The common "nothing is due" path is a
    single indexed SELECT; savepoints are only opened when there is work.)
    """
    from hrms.modules.people.router import apply_due_actions

    try:
        await apply_due_actions(session, tenant_id)
    except Exception:
        logger.exception("Applying scheduled personnel actions failed for tenant %s", tenant_id)


SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


async def get_anonymous_session() -> AsyncGenerator[AsyncSession, None]:
    """
    For POST /v1/auth/login only — the one request that runs before any
    tenant or user identity is known. app.tenant_id is deliberately left
    unset, so ordinary RLS-scoped tables return nothing through this
    session; the login handler may only call the login_lookup() SECURITY
    DEFINER function (migration 0005), which exposes just the columns
    login needs and nothing else.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            _finish_files(session, committed=True)
        except Exception:
            await session.rollback()
            _finish_files(session, committed=False)
            raise


AnonymousSessionDep = Annotated[AsyncSession, Depends(get_anonymous_session, scope="function")]


def _finish_files(session, committed):
    import logging

    for path in session.info.pop("delete_files" if committed else "created_files", []):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).exception("Could not remove document file")
    session.info.pop("created_files" if committed else "delete_files", None)

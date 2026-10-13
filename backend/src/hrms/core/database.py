"""
Async SQLAlchemy engine + session factory with per-transaction tenant isolation.

Every session runs SET LOCAL app.tenant_id = '<uuid>' before any statement so
PostgreSQL row-level security policies can read the tenant from current_setting().
This is a real second layer, not just decoration: the engine connects as
hrms_app (see migration 0005), a role with NOSUPERUSER and NOBYPASSRLS, so a
bug that forgets a WHERE tenant_id = ... clause still can't read another
tenant's rows — Postgres itself refuses.
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from hrms.core.authn import CurrentUser
from hrms.core.config import settings
from hrms.core.datetime_utils import business_today
from hrms.core.errors import CodedHTTPException
from hrms.core.tenancy import TenantDep

logger = logging.getLogger(__name__)

# A user who must change their password (freshly imported, or reset by an
# admin) may only reach these until they have. Everything else is refused
# server-side — the frontend redirect is a convenience, not the control.
PASSWORD_CHANGE_EXEMPT_PATHS = frozenset(
    {"/v1/auth/change-password", "/v1/auth/me", "/v1/auth/logout"}
)

# session.info key: (user_account_id, live role grants) read by get_session in the same
# round trip as the account checks, so core/authz.resolve_scope needn't query them again.
GRANTS_KEY = "hrms_role_grants"

engine = create_async_engine(
    settings.app_database_url or settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    pool_timeout=settings.database_pool_timeout_seconds,
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
        # Everything "may this token still act?" needs, in one round trip:
        # - Suspension/archival is checked here too, not just at login — a platform admin
        #   suspending a tenant mid-session cuts off its already-issued tokens on their very
        #   next request, not after token expiry. (tenants has no RLS.)
        # - The account and its employment are read live, so a separation locks the person
        #   out from the moment it's applied and a rehire lets them back in, with no account
        #   flag to keep in sync.
        # - The caller's live role grants, for get_current_scope (session.info, below).
        # - Whether any scheduled personnel action is due, so the common "nothing due" case
        #   costs no extra query. business_today() matches apply_due_actions exactly.
        auth = (
            (
                await session.execute(
                    text("""
            SELECT t.status AS tenant_status, t.archived_at AS tenant_archived_at,
                   ua.id IS NOT NULL AS account_found, ua.status, ua.employment_id,
                   ua.must_change_password, ua.token_epoch, ua.mfa_secret, e.employment_state,
                   EXISTS (
                       SELECT 1 FROM personnel_actions pa
                       WHERE pa.tenant_id = t.id AND pa.status = 'SCHEDULED'
                         AND pa.effective_date <= :today
                   ) AS actions_due,
                   (
                       SELECT COALESCE(
                           json_agg(json_build_array(r.name, ra.scope_type, ra.scope_value)),
                           '[]'
                       )
                       FROM role_assignments ra
                       JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                       WHERE ra.tenant_id = t.id AND ra.user_account_id = ua.id
                         AND (ra.expires_at IS NULL OR ra.expires_at > now())
                   ) AS grants,
                   (
                       -- A session a connected app obtained for this employee lives only while
                       -- the app's key does (NULL for ordinary sign-ins).
                       SELECT k.is_active AND k.revoked_at IS NULL
                              AND (k.expires_at IS NULL OR k.expires_at > now())
                              AND ca.status = 'ACTIVE'
                       FROM api_keys k
                       JOIN connected_apps ca ON ca.tenant_id = k.tenant_id AND ca.id = k.app_id
                       WHERE k.tenant_id = t.id AND k.id = CAST(:via AS uuid)
                   ) AS via_ok,
                   (
                       SELECT k.app_id FROM api_keys k
                       WHERE k.tenant_id = t.id AND k.id = CAST(:via AS uuid)
                   ) AS via_app_id
            FROM tenants t
            LEFT JOIN user_accounts ua
                   ON ua.tenant_id = t.id AND ua.id = CAST(:uid AS uuid)
            LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
            WHERE t.id = CAST(:tid AS uuid)
        """),
                    {
                        "tid": str(tenant_id),
                        "uid": str(principal.user_account_id),
                        "today": business_today(),
                        "via": str(principal.via_key_id) if principal.via_key_id else None,
                    },
                )
            )
            .mappings()
            .first()
        )
        if not auth or auth["tenant_status"] != "ACTIVE" or auth["tenant_archived_at"] is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This company's account is suspended")
        account = auth
        if (
            not account["account_found"]
            or account["status"] != "ACTIVE"
            or account["employment_id"] != principal.employment_id
            or account["employment_state"] == "SEPARATED"
        ):
            raise HTTPException(401, "This account is no longer active; sign in again")
        if account["token_epoch"] != principal.token_epoch:
            raise HTTPException(401, "Your password was changed; sign in again")
        grants = auth["grants"]
        parsed_grants = json.loads(grants) if isinstance(grants, str) else grants
        if principal.via_key_id is not None:
            # A session a connected app obtained for this employee (plan §8.3): the employee
            # authenticated in the app, so no forced password change here; only self-service
            # routes; never more than EMPLOYEE/MANAGER rights, so MFA never applies.
            await _check_app_session(session, tenant_id, request, auth, principal)
            from hrms.modules.integrations.session_policy import SESSION_ROLES

            parsed_grants = [g for g in parsed_grants if g[0] in SESSION_ROLES]
        elif (
            account["must_change_password"]
            and request.url.path not in PASSWORD_CHANGE_EXEMPT_PATHS
        ):
            raise CodedHTTPException(
                status.HTTP_403_FORBIDDEN,
                "You must change your password before continuing",
                code="PASSWORD_CHANGE_REQUIRED",
            )
        from hrms.core.config import settings
        from hrms.core.mfa import EXEMPT_PATHS, PRIVILEGED_ROLES

        required = principal.via_key_id is None and (
            bool(auth["mfa_secret"])
            or (
                settings.privileged_mfa_required
                and any(g[0] in PRIVILEGED_ROLES for g in parsed_grants)
            )
        )
        if required and not principal.mfa_verified and request.url.path not in EXEMPT_PATHS:
            raise CodedHTTPException(
                403, "Set up your authenticator and sign in again", code="MFA_SETUP_REQUIRED"
            )
        session.info[GRANTS_KEY] = (
            principal.user_account_id,
            [
                {"role_name": g[0], "scope_type": g[1], "scope_value": g[2]}
                for g in parsed_grants
            ],
        )
        try:
            if auth["actions_due"]:
                await _apply_scheduled_actions(session, tenant_id)
                state = (
                    await session.execute(
                        text("""
                    SELECT ua.status, e.employment_state
                    FROM user_accounts ua LEFT JOIN employments e
                      ON e.tenant_id=ua.tenant_id AND e.id=ua.employment_id
                    WHERE ua.tenant_id=:tid AND ua.id=:uid
                """),
                        {"tid": tenant_id, "uid": principal.user_account_id},
                    )
                ).first()
                if not state or state.status != "ACTIVE" or state.employment_state == "SEPARATED":
                    raise HTTPException(401, "This account is no longer active; sign in again")
            yield session
            await session.commit()
            await _finish_files(session, committed=True)
        except Exception:
            await session.rollback()
            await _finish_files(session, committed=False)
            raise


async def _check_app_session(session: AsyncSession, tenant_id, request: Request, auth, principal):
    from hrms.modules.integrations.profiles import effective_settings
    from hrms.modules.integrations.session_policy import route_features

    if not auth["via_ok"]:
        raise CodedHTTPException(
            401,
            "This session was issued through an app whose access has ended",
            code="APP_SESSION_REVOKED",
        )
    listed, features = route_features(request.method, request.url.path)
    if not listed:
        raise CodedHTTPException(
            403,
            "This isn't available through a connected app. Sign in to HRMS to use it.",
            code="NOT_AVAILABLE_VIA_INTEGRATION",
        )
    if features:
        legal_entity_id = (
            await session.execute(
                text(
                    "SELECT legal_entity_id FROM employments WHERE tenant_id = :tid AND id = :eid"
                ),
                {"tid": tenant_id, "eid": principal.employment_id},
            )
        ).scalar()
        options = (
            await effective_settings(session, tenant_id, auth["via_app_id"], legal_entity_id)
        ).self_service
        if not any(getattr(options, f) for f in features):
            raise CodedHTTPException(
                403,
                "This feature is switched off for this app",
                code="NOT_AVAILABLE_VIA_INTEGRATION",
            )


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
        async with session.begin_nested():
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
            await _finish_files(session, committed=True)
        except Exception:
            await session.rollback()
            await _finish_files(session, committed=False)
            raise


AnonymousSessionDep = Annotated[AsyncSession, Depends(get_anonymous_session, scope="function")]


async def _finish_files(session, committed):
    import logging

    from starlette.concurrency import run_in_threadpool

    from hrms.core import document_store

    for ref in session.info.pop("delete_files" if committed else "created_files", []):
        try:
            await run_in_threadpool(document_store.remove, str(ref))
        except Exception:
            logging.getLogger(__name__).exception("Could not remove document file")
    session.info.pop("created_files" if committed else "delete_files", None)

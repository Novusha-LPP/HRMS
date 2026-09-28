"""
Authentication.

POST /v1/auth/login            — email + password -> access token (the ONLY
                                  way a client establishes tenant +
                                  employment identity)
GET  /v1/auth/me                — the caller's own profile, roles and
                                  accessible companies, derived from the
                                  verified token
POST /v1/auth/register-company — bootstrap a brand-new, fully isolated
                                  tenant (see register_company below)

Login runs before any tenant is known, so it uses a tenant-free session and
the login_lookup() SECURITY DEFINER function (migration 0005) rather than an
ordinary RLS-scoped query — see core/database.get_anonymous_session.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.authn import CurrentUser, Principal
from hrms.core.authz import Scope, resolve_scope
from hrms.core.config import settings
from hrms.core.database import AnonymousSessionDep, SessionDep
from hrms.core.ids import to_typed_id
from hrms.core.security import create_access_token, verify_password
from hrms.core.tenant_provisioning import bootstrap_tenant
from hrms.modules.kernel.auth.schemas import (
    LegalEntitySummary,
    LoginRequest,
    LoginResponse,
    MeResponse,
    TenantRegister,
)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse, summary="Sign in with email and password")
async def login(body: LoginRequest, session: AnonymousSessionDep) -> LoginResponse:
    row = (
        (await session.execute(text("SELECT * FROM login_lookup(:email)"), {"email": body.email}))
        .mappings()
        .first()
    )

    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not row or row["status"] != "ACTIVE":
        raise invalid
    if not verify_password(body.password, row["password_hash"]):
        raise invalid

    tenant_id: UUID = row["tenant_id"]
    account_id: UUID = row["id"]
    employment_id: UUID | None = row["employment_id"]

    # tenants has no RLS (see migration 0005's comment), so this plain SELECT
    # works even before app.tenant_id is set below — a platform admin's
    # "Suspend" or "Archive" action (POST /v1/platform/tenants/...) has to
    # actually stop logins for it to mean anything, not just change a
    # cosmetic badge.
    tenant_row = (
        (
            await session.execute(
                text("SELECT status, archived_at FROM tenants WHERE id = :tid"),
                {"tid": str(tenant_id)},
            )
        )
        .mappings()
        .first()
    )
    if not tenant_row or tenant_row["status"] != "ACTIVE" or tenant_row["archived_at"] is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This company's account is suspended")

    # Everything after this point is a normal tenant-scoped query, so set the
    # session's tenant context exactly like get_session() does.
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )
    await session.execute(
        text("""
            UPDATE user_accounts SET last_login_at = :now
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)
        """),
        {"now": datetime.now(UTC), "tid": str(tenant_id), "uid": str(account_id)},
    )

    principal = Principal(
        tenant_id=tenant_id,
        user_account_id=account_id,
        employment_id=employment_id,
        role_names=frozenset(),
    )
    scope = await resolve_scope(session, tenant_id, principal)
    user = await _build_me_response(session, tenant_id, account_id, employment_id, scope)

    token = create_access_token(
        user_account_id=account_id,
        tenant_id=tenant_id,
        employment_id=employment_id,
        role_names=list(scope.role_names),
    )

    return LoginResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


@router.post(
    "/register-company",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a brand-new company as its own isolated tenant",
)
async def register_company(body: TenantRegister, session: AnonymousSessionDep) -> LoginResponse:
    """
    This is NOT "add a sister company" (POST /v1/org/legal-entities) — that
    adds a legal entity inside the CALLER's existing tenant, and requires
    already being signed in as that tenant's admin. This is a different
    tenant altogether: a new isolation boundary with its own roles, its own
    first company, and a first SUPER_ADMIN login that can never see (and is
    never visible to) SFPL Group or any other tenant. See also
    POST /v1/platform/companies, which a platform admin uses to do the same
    thing (or link a company under an EXISTING tenant instead) without
    becoming that tenant's user themselves.
    """
    tenant_id, _legal_entity_id, account_id = await bootstrap_tenant(
        session,
        company_name=body.company_name,
        country_code=body.country_code,
        admin_email=body.admin_email,
        admin_password=body.admin_password,
    )

    principal = Principal(
        tenant_id=tenant_id, user_account_id=account_id, employment_id=None, role_names=frozenset()
    )
    scope = await resolve_scope(session, tenant_id, principal)
    user = await _build_me_response(session, tenant_id, account_id, None, scope)

    token = create_access_token(
        user_account_id=account_id,
        tenant_id=tenant_id,
        employment_id=None,
        role_names=list(scope.role_names),
    )
    return LoginResponse(
        access_token=token, expires_in=settings.access_token_expire_minutes * 60, user=user
    )


@router.get("/me", response_model=MeResponse, summary="The signed-in user's profile and access")
async def me(principal: CurrentUser, session: SessionDep) -> MeResponse:
    scope = await resolve_scope(session, principal.tenant_id, principal)
    return await _build_me_response(
        session, principal.tenant_id, principal.user_account_id, principal.employment_id, scope
    )


async def _build_me_response(
    session: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    employment_id: UUID | None,
    scope: Scope,
) -> MeResponse:
    account_row = (
        (
            await session.execute(
                text(
                    "SELECT email FROM user_accounts WHERE tenant_id = CAST(:tid AS uuid) "
                    "AND id = CAST(:uid AS uuid)"
                ),
                {"tid": str(tenant_id), "uid": str(account_id)},
            )
        )
        .mappings()
        .first()
    )
    email = account_row["email"] if account_row else None

    tenant_row = (
        (
            await session.execute(
                text("SELECT display_name FROM tenants WHERE id = CAST(:tid AS uuid)"),
                {"tid": str(tenant_id)},
            )
        )
        .mappings()
        .first()
    )
    tenant_name = tenant_row["display_name"] if tenant_row else "Workspace"

    name = email or "Unnamed user"
    if employment_id:
        person_row = (
            (
                await session.execute(
                    text("""
                    SELECT COALESCE(p.preferred_name, p.legal_first_name) AS first,
                    p.legal_last_name AS last
                    FROM employments e JOIN persons p ON p.tenant_id = e.tenant_id AND p.id =
                    e.person_id
                    WHERE e.tenant_id = CAST(:tid AS uuid) AND e.id = CAST(:eid AS uuid)
                """),
                    {"tid": str(tenant_id), "eid": str(employment_id)},
                )
            )
            .mappings()
            .first()
        )
        if person_row:
            name = f"{person_row['first']} {person_row['last']}"

    if scope.is_all:
        entity_rows = await session.execute(
            text("""
                SELECT id, name FROM legal_entities
                WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL ORDER BY name
            """),
            {"tid": str(tenant_id)},
        )
    elif scope.legal_entity_ids:
        entity_rows = await session.execute(
            text("""
                SELECT id, name FROM legal_entities
                WHERE tenant_id = CAST(:tid AS uuid) AND archived_at IS NULL
                  AND id = ANY(CAST(:ids AS uuid[])) ORDER BY name
            """),
            {"tid": str(tenant_id), "ids": [str(i) for i in scope.legal_entity_ids]},
        )
    elif employment_id:
        entity_rows = await session.execute(
            text("""
                SELECT le.id, le.name FROM employments e
                JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                WHERE e.tenant_id = CAST(:tid AS uuid) AND e.id = CAST(:eid AS uuid)
            """),
            {"tid": str(tenant_id), "eid": str(employment_id)},
        )
    else:
        entity_rows = []

    legal_entities = [
        LegalEntitySummary(id=to_typed_id("legal_entity", r[0]), name=r[1]) for r in entity_rows
    ]

    return MeResponse(
        id=to_typed_id("user", account_id),
        email=email,
        name=name,
        employment_id=to_typed_id("employment", employment_id) if employment_id else None,
        tenant_id=to_typed_id("tenant", tenant_id),
        tenant_name=tenant_name,
        roles=sorted(scope.role_names),
        permissions=sorted(scope.permissions),
        is_all_scope=scope.is_all,
        legal_entities=legal_entities,
    )

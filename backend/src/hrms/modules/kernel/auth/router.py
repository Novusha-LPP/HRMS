"""
Authentication.

POST /v1/auth/login            — identifier (email, employee code or mobile) +
                                  password -> access token (the ONLY way a
                                  client establishes tenant + employment identity)
POST /v1/auth/change-password  — the signed-in user replaces their password;
                                  returns a fresh token, every older one stops working
GET  /v1/auth/me                — the caller's own profile, roles and
                                  accessible companies, derived from the
                                  verified token
POST /v1/auth/register-company — bootstrap a brand-new, fully isolated
                                  tenant (see register_company below)

Login runs before any tenant is known, so it uses a tenant-free session and
the login_lookup() SECURITY DEFINER function (migrations 0005/0019) rather than
an ordinary RLS-scoped query — see core/database.get_anonymous_session.

Login hardening (all of it lives here or in core/throttle.py):
  - attempts are counted per identifier+IP, per identifier and per IP, and a
    locked key answers 429 before any password work happens;
  - password checks run in a worker thread (bcrypt would otherwise freeze the
    event loop for every other request), and a miss spends the same time as a
    hit so response time can't reveal which identifiers exist;
  - an identifier that matches several accounts (a shared phone, the same
    employee code in two companies) is settled by the password, never by guessing.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core import throttle
from hrms.core.authn import CurrentUser, Principal
from hrms.core.authz import Scope, resolve_scope
from hrms.core.browser_sessions import clear_browser_session, issue_browser_session
from hrms.core.config import settings
from hrms.core.database import AnonymousSessionDep, SessionDep
from hrms.core.errors import CodedHTTPException
from hrms.core.ids import to_typed_id
from hrms.core.mfa import ConfirmRequest, EnrollRequest
from hrms.core.security import (
    ahash_password,
    averify_password,
    create_access_token,
    spend_verification_time,
)
from hrms.core.tenant_provisioning import bootstrap_tenant
from hrms.modules.kernel.auth.schemas import (
    ChangePasswordRequest,
    LegalEntitySummary,
    LoginRequest,
    LoginResponse,
    MeResponse,
    TenantRegister,
)

router = APIRouter(prefix="/v1/auth", tags=["Auth"])

# More candidates than this are never tried: each one costs a bcrypt check.
_MAX_CANDIDATES_CHECKED = 3


@router.post("/login", response_model=LoginResponse, summary="Sign in")
async def login(
    body: LoginRequest, request: Request, response: Response, session: AnonymousSessionDep
) -> LoginResponse:
    identifier = body.identifier.strip()
    ip = throttle.client_ip(request)
    await throttle.check_login_allowed(identifier, ip)

    if body.tenant and body.tenant.strip():
        lookup, params = (
            "SELECT * FROM login_lookup_in(:identifier, :slug)",
            {"identifier": identifier, "slug": body.tenant.strip()},
        )
    else:
        lookup, params = "SELECT * FROM login_lookup(:identifier)", {"identifier": identifier}
    candidates = (await session.execute(text(lookup), params)).mappings().all()
    usable = [c for c in candidates if c["status"] == "ACTIVE" and c["password_hash"]]

    company_required = CodedHTTPException(
        status.HTTP_409_CONFLICT,
        "More than one company uses this sign-in. Enter your company code.",
        code="COMPANY_REQUIRED",
    )
    if len(usable) > _MAX_CANDIDATES_CHECKED:
        # Too many to try one by one (each try costs a bcrypt check) — ask, don't guess.
        raise company_required

    matches = []
    if usable:
        for candidate in usable:
            if await averify_password(body.password, candidate["password_hash"]):
                matches.append(candidate)
    else:
        await spend_verification_time(body.password)

    if len(matches) > 1:
        # The password is right for accounts in several companies: only a company code can
        # tell them apart. (Reaching this means the caller knows a valid password for each,
        # so saying so reveals nothing they don't already have.)
        raise company_required
    if not matches:  # unknown identifier, or wrong password
        await throttle.record_login_failure(identifier, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    row = matches[0]

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

    # The password was right, so it's safe to say why entry is refused. A
    # separated employee is locked out here exactly as get_session() locks out
    # their existing tokens.
    state = (
        (
            await session.execute(
                text("""
                    SELECT ua.id,ua.token_epoch,ua.mfa_secret,ua.mfa_last_step,e.employment_state
                    FROM user_accounts ua
                    LEFT JOIN employments e
                      ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
                    WHERE ua.tenant_id = CAST(:tid AS uuid) AND ua.id = CAST(:uid AS uuid)
                """),
                {"tid": str(tenant_id), "uid": str(account_id)},
            )
        )
        .mappings()
        .one()
    )
    if state["employment_state"] == "SEPARATED":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is no longer active")

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

    from hrms.core.mfa import verify_login

    try:
        mfa_verified = await verify_login(session, state, body.otp, tenant_id=tenant_id)
    except CodedHTTPException:
        await throttle.record_login_failure(identifier, ip)
        raise
    user.mfa_required = user.mfa_required and not mfa_verified
    token = create_access_token(
        mfa_verified=mfa_verified,
        user_account_id=account_id,
        tenant_id=tenant_id,
        employment_id=employment_id,
        role_names=list(scope.role_names),
        token_epoch=state["token_epoch"],
    )
    await throttle.record_login_success(identifier, ip)

    return LoginResponse(
        access_token=issue_browser_session(
            request, response, token, settings.access_token_expire_minutes * 60
        ),
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


@router.post(
    "/change-password",
    response_model=LoginResponse,
    summary="Replace your own password",
)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    principal: CurrentUser,
    session: SessionDep,
) -> LoginResponse:
    """
    Works even while a password change is being *required* (imported and
    admin-reset accounts). Every token issued before this call is rejected
    from now on, so the response carries a fresh one — the caller stays signed
    in, anyone else holding the old password or token does not.
    """
    tenant_id, account_id = principal.tenant_id, principal.user_account_id
    throttle_key = str(account_id)
    await throttle.ensure_not_locked("pwchange", throttle_key)

    current_hash = (
        await session.execute(
            text("""
                SELECT password_hash FROM user_accounts
                WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)
            """),
            {"tid": str(tenant_id), "uid": str(account_id)},
        )
    ).scalar()
    if not await averify_password(body.current_password, current_hash):
        await throttle.record_attempt(
            "pwchange",
            throttle_key,
            max_attempts=settings.login_max_failures,
            window_minutes=settings.login_lockout_minutes,
            lock_minutes=settings.login_lockout_minutes,
        )
        # 400, not 401: the frontend treats 401 as "session over" and logs out.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Choose a password different from your current one"
        )

    new_hash = await ahash_password(body.new_password)
    new_epoch = (
        await session.execute(
            text("""
                UPDATE user_accounts
                SET password_hash = :hash, must_change_password = false,
                    password_changed_at = :changed_at, token_epoch = token_epoch + 1,
                    version = version + 1
                WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)
                RETURNING token_epoch
            """),
            {
                "hash": new_hash,
                "changed_at": datetime.now(UTC),
                "tid": str(tenant_id),
                "uid": str(account_id),
            },
        )
    ).scalar_one()
    await throttle.clear("pwchange", throttle_key)

    scope = await resolve_scope(session, tenant_id, principal)
    user = await _build_me_response(session, tenant_id, account_id, principal.employment_id, scope)
    user.mfa_required = user.mfa_required and not principal.mfa_verified
    # Carries the new epoch, so it is the one token that survives the change.
    token = create_access_token(
        user_account_id=account_id,
        tenant_id=tenant_id,
        employment_id=principal.employment_id,
        role_names=list(scope.role_names),
        token_epoch=new_epoch,
        mfa_verified=principal.mfa_verified,
    )
    return LoginResponse(
        access_token=issue_browser_session(
            request, response, token, settings.access_token_expire_minutes * 60
        ),
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


@router.post(
    "/register-company",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a brand-new company as its own isolated tenant",
)
async def register_company(
    body: TenantRegister, request: Request, response: Response, session: AnonymousSessionDep
) -> LoginResponse:
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

    Anonymous, so it is rate-limited per client IP (settings.register_max_per_hour)
    and can be switched off entirely (HRMS_ALLOW_PUBLIC_REGISTRATION=false) for
    deployments where tenants are only created from the platform console.
    """
    if not settings.allow_public_registration:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Self-service registration is disabled on this deployment"
        )
    ip = throttle.client_ip(request)
    await throttle.check_registration_allowed(ip)
    await throttle.record_registration(ip)

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
        access_token=issue_browser_session(
            request, response, token, settings.access_token_expire_minutes * 60
        ),
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


@router.get("/me", response_model=MeResponse, summary="The signed-in user's profile and access")
async def me(principal: CurrentUser, session: SessionDep) -> MeResponse:
    scope = await resolve_scope(session, principal.tenant_id, principal)
    result = await _build_me_response(
        session, principal.tenant_id, principal.user_account_id, principal.employment_id, scope
    )
    result.mfa_required = result.mfa_required and not principal.mfa_verified
    return result


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
                    "SELECT email, employee_code, must_change_password,mfa_secret "
                    "FROM user_accounts "
                    "WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)"
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

    name = email or (account_row["employee_code"] if account_row else None) or "Unnamed user"
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
        entity_rows = []  # type: ignore[assignment]  # nothing to list; iterated like a Result

    legal_entities = [
        LegalEntitySummary(id=to_typed_id("legal_entity", r[0]), name=r[1]) for r in entity_rows
    ]

    return MeResponse(
        mfa_required=bool(account_row and account_row["mfa_secret"])
        or (
            settings.privileged_mfa_required
            and bool(scope.role_names & {"SUPER_ADMIN", "HR_MANAGER", "ACCOUNTANT"})
        ),
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
        must_change_password=bool(account_row["must_change_password"]) if account_row else False,
    )


@router.post("/logout", status_code=204)
async def logout(principal: CurrentUser, session: SessionDep, response: Response) -> None:
    await session.execute(
        text("UPDATE user_accounts SET token_epoch=token_epoch+1 WHERE tenant_id=:tid AND id=:uid"),
        {"tid": principal.tenant_id, "uid": principal.user_account_id},
    )
    clear_browser_session(response)


@router.post("/mfa/enroll")
async def enroll_mfa(
    body: EnrollRequest, principal: CurrentUser, session: SessionDep, response: Response
):
    from hrms.core.mfa import enroll

    response.headers["Cache-Control"] = "no-store"
    return await enroll(
        session, principal.user_account_id, body.password, tenant_id=principal.tenant_id
    )


@router.post("/mfa/confirm", status_code=204)
async def confirm_mfa(
    body: ConfirmRequest, principal: CurrentUser, session: SessionDep, response: Response
):
    from hrms.core.mfa import confirm

    await confirm(session, principal.user_account_id, body.code, tenant_id=principal.tenant_id)
    clear_browser_session(response)

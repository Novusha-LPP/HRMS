"""
Platform administration — /v1/platform/*.

This is a role ABOVE every tenant, not another tenant-scoped SUPER_ADMIN.
Every ordinary SUPER_ADMIN is a role_assignment inside one tenant; its JWT
carries that tenant's id and RLS enforces the boundary from there, so it can
never reach a second tenant no matter what permission it holds (see
core/authz.py). A platform admin authenticates through an entirely separate
table (platform_admins) and token type (core/security.PLATFORM_TOKEN_TYPE)
that the ordinary tenant-scoped dependencies don't even recognise.

Two enforcement layers beyond identity:
  - Role (core/platform_authz.py): ADMIN can read and write; VIEWER is
    read-only. Resolved fresh from the DB on every request, not baked into
    the JWT, so a demotion or suspension takes effect on the very next
    request rather than waiting out an up-to-8h token.
  - Audit (core/audit.py): every mutating action here is logged — actor,
    action, target, timestamp, and a small metadata blob (e.g. old/new
    plan). Nothing here is ever updated or deleted.

Scope, deliberately narrow: registering/linking companies, tenant standing
(suspend/plan/archive), and platform-admin management. NOT visibility into
any tenant's actual HR data (employees, leave, payroll, ...) — the one
exception is a bare employee COUNT on tenant detail (a usage signal, not the
data itself), computed the same RLS-bypassing way as the company count.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from hrms.core import throttle
from hrms.core.audit import record_audit
from hrms.core.config import settings
from hrms.core.database import AnonymousSessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.platform_authz import (
    CurrentPlatformAdminCtx,
    PlatformAdminContext,
    require_platform_role,
)
from hrms.core.security import (
    ahash_password,
    averify_password,
    create_platform_token,
    generate_reset_token,
    hash_reset_token,
    spend_verification_time,
)
from hrms.core.tenant_provisioning import bootstrap_tenant
from hrms.modules.org.models import LegalEntity
from hrms.modules.platform.schemas import (
    AuditLogEntry,
    AuditLogResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    PlatformAdminCreate,
    PlatformAdminSummary,
    PlatformAdminUpdate,
    PlatformCompanyCreate,
    PlatformCompanyResponse,
    PlatformLoginRequest,
    PlatformLoginResponse,
    PlatformMe,
    ResetPasswordRequest,
    TenantDetail,
    TenantLegalEntity,
    TenantListResponse,
    TenantSummary,
    TenantUpdate,
)

router = APIRouter(prefix="/v1/platform", tags=["Platform"])

RESET_TOKEN_TTL_MINUTES = 60
PLATFORM_LOGIN_REALM = "platform-login"


@router.post("/login", response_model=PlatformLoginResponse, summary="Platform admin sign-in")
async def platform_login(
    body: PlatformLoginRequest, request: Request, session: AnonymousSessionDep
) -> PlatformLoginResponse:
    # The console that can see and change every tenant: same brute-force protection and
    # timing discipline as tenant sign-in (see modules/kernel/auth/router.py).
    ip = throttle.client_ip(request)
    await throttle.check_login_allowed(body.email, ip, PLATFORM_LOGIN_REALM)
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, name, role, password_hash, status, token_epoch "
                    "FROM platform_admins "
                    "WHERE lower(email) = lower(:email)"
                ),
                {"email": body.email},
            )
        )
        .mappings()
        .first()
    )

    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if row and row["status"] == "ACTIVE" and row["password_hash"]:
        password_ok = await averify_password(body.password, row["password_hash"])
    else:
        await spend_verification_time(body.password)
        password_ok = False
    if not password_ok:
        await throttle.record_login_failure(body.email, ip, PLATFORM_LOGIN_REALM)
        raise invalid
    await throttle.record_login_success(body.email, ip, PLATFORM_LOGIN_REALM)

    admin_id: UUID = row["id"]
    await session.execute(
        text("UPDATE platform_admins SET last_login_at = :now WHERE id = :id"),
        {"now": datetime.now(UTC), "id": str(admin_id)},
    )

    token = create_platform_token(admin_id=admin_id, token_epoch=row["token_epoch"])
    return PlatformLoginResponse(
        access_token=token,
        expires_in=settings.platform_token_expire_minutes * 60,
        name=row["name"],
        email=body.email,
        role=row["role"],
    )


@router.get(
    "/me",
    response_model=PlatformMe,
    summary="The signed-in platform admin's current name/email/role",
)
async def platform_me(admin: CurrentPlatformAdminCtx) -> PlatformMe:
    """
    The frontend calls this on load rather than trusting whatever it cached
    at login — role (and status) are resolved fresh from the DB per request
    everywhere else in this router, and the UI should match: if another
    admin promotes or demotes this account, or a client's cached login
    predates a field being added here, the very next page load reflects the
    current truth instead of a stale login response.
    """
    return PlatformMe(name=admin.name, email=admin.email, role=admin.role)


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Request a password reset link",
)
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, session: AnonymousSessionDep
) -> ForgotPasswordResponse:
    """
    Always returns the same generic message regardless of whether the email
    exists, so this can't be used to enumerate platform admin accounts.
    SES delivery is queued transactionally and retried by the jobs worker.
    Local debug mode can return the link directly; disabled recovery returns 503.
    """
    if settings.mail_backend == "disabled" and not settings.debug:
        raise HTTPException(503, "Password recovery is not configured; contact an administrator")
    # Anonymous, and each real request writes a token row — cap it per address.
    await throttle.rate_limit("platform-forgot:ip", throttle.client_ip(request), max_per_hour=10)
    generic = ForgotPasswordResponse(
        message="If that email has an account, a reset link has been generated."
    )

    row = (
        (
            await session.execute(
                text("SELECT id, status FROM platform_admins WHERE lower(email) = lower(:email)"),
                {"email": body.email},
            )
        )
        .mappings()
        .first()
    )
    if not row or row["status"] != "ACTIVE":
        return generic

    token = generate_reset_token()
    from hrms.core.mail import reset_payload

    delivery = reset_payload(body.email, token) if settings.mail_backend == "ses" else None
    await session.execute(
        text("""
            INSERT INTO platform_password_reset_tokens
                (id, admin_id, token_hash, expires_at, delivery_payload)
            VALUES (:id, :admin_id, :hash, :expires, :delivery)
        """),
        {
            "id": str(uuid4()),
            "admin_id": str(row["id"]),
            "hash": hash_reset_token(token),
            "delivery": delivery,
            "expires": datetime.now(UTC) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        },
    )

    if settings.debug:
        generic.dev_reset_url = f"/platform/reset-password?token={token}"
    return generic


@router.post("/reset-password", summary="Complete a password reset")
async def reset_password(
    body: ResetPasswordRequest, session: AnonymousSessionDep
) -> dict[str, str]:
    token_hash = hash_reset_token(body.token)
    row = (
        (
            await session.execute(
                text("""
                SELECT id, admin_id, expires_at, used_at FROM platform_password_reset_tokens
                WHERE token_hash = :hash
            """),
                {"hash": token_hash},
            )
        )
        .mappings()
        .first()
    )

    invalid = HTTPException(
        status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired"
    )
    if not row:
        raise invalid
    # Serialize all reset links for one administrator before locking a token row.
    # This prevents two different links changing credentials concurrently/deadlocking.
    await session.execute(
        text("SELECT id FROM platform_admins WHERE id=:id FOR UPDATE"), {"id": row["admin_id"]}
    )
    row = (
        (
            await session.execute(
                text("""SELECT id, admin_id, expires_at, used_at
        FROM platform_password_reset_tokens WHERE token_hash=:hash FOR UPDATE"""),
                {"hash": token_hash},
            )
        )
        .mappings()
        .one()
    )
    if row["used_at"] is not None:
        raise invalid
    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise invalid

    await session.execute(
        text(
            "UPDATE platform_admins SET password_hash = :pw, "
            "token_epoch = token_epoch + 1 WHERE id = :id"
        ),
        {"pw": await ahash_password(body.new_password), "id": str(row["admin_id"])},
    )
    await session.execute(
        text(
            "UPDATE platform_password_reset_tokens SET used_at = :now, "
            "delivery_payload=NULL WHERE admin_id = :id AND used_at IS NULL"
        ),
        {"now": datetime.now(UTC), "id": str(row["admin_id"])},
    )
    return {"message": "Password updated — you can sign in now."}


@router.get("/tenants", response_model=TenantListResponse, summary="List tenants on the platform")
async def list_tenants(
    _admin: CurrentPlatformAdminCtx,
    session: AnonymousSessionDep,
    q: str | None = None,
    include_archived: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> TenantListResponse:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    archive_clause = "" if include_archived else "AND archived_at IS NULL"
    search_clause = "AND display_name ILIKE :q" if q else ""
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if q:
        params["q"] = f"%{q}%"

    rows = (
        (
            await session.execute(
                text(f"""
                SELECT * FROM platform_list_tenants()
                WHERE TRUE {archive_clause} {search_clause}
                ORDER BY display_name LIMIT :limit OFFSET :offset
            """),
                params,
            )
        )
        .mappings()
        .all()
    )
    total = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM platform_list_tenants() "
                f"WHERE TRUE {archive_clause} {search_clause}"
            ),
            {k: v for k, v in params.items() if k != "limit" and k != "offset"},
        )
    ).scalar_one()

    return TenantListResponse(
        total=total,
        items=[
            TenantSummary(
                id=to_typed_id("tenant", r["id"]),
                slug=r["slug"],
                display_name=r["display_name"],
                status=r["status"],
                plan=r["plan"],
                legal_entity_count=r["legal_entity_count"],
                created_at=r["created_at"],
                archived_at=r["archived_at"],
            )
            for r in rows
        ],
    )


async def _tenant_detail(tenant_id_str: str, session) -> TenantDetail:
    tid = to_uuid(tenant_id_str)
    tenant_row = (
        (
            await session.execute(
                text(
                    "SELECT id, slug, display_name, status, plan, country_code, created_at, "
                    "archived_at FROM tenants WHERE id = :id"
                ),
                {"id": str(tid)},
            )
        )
        .mappings()
        .first()
    )
    if not tenant_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tenant")

    # legal_entities/employments are RLS-protected; bind this session to the
    # tenant being inspected so the reads pass, same trick used when linking
    # a subsidiary or bootstrapping a new tenant.
    await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)})
    entity_rows = (
        (
            await session.execute(
                text("""
                SELECT id, name, short_name, status FROM legal_entities
                WHERE tenant_id = :tid AND archived_at IS NULL ORDER BY name
            """),
                {"tid": str(tid)},
            )
        )
        .mappings()
        .all()
    )
    employee_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM employments WHERE tenant_id = :tid"), {"tid": str(tid)}
        )
    ).scalar_one()

    return TenantDetail(
        id=to_typed_id("tenant", tenant_row["id"]),
        slug=tenant_row["slug"],
        display_name=tenant_row["display_name"],
        status=tenant_row["status"],
        plan=tenant_row["plan"],
        country_code=tenant_row["country_code"],
        legal_entity_count=len(entity_rows),
        employee_count=employee_count,
        created_at=tenant_row["created_at"],
        archived_at=tenant_row["archived_at"],
        legal_entities=[
            TenantLegalEntity(
                id=to_typed_id("legal_entity", r["id"]),
                name=r["name"],
                short_name=r["short_name"],
                status=r["status"],
            )
            for r in entity_rows
        ],
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantDetail,
    summary="Tenant detail — its companies and current standing",
)
async def get_tenant(
    tenant_id: str, _admin: CurrentPlatformAdminCtx, session: AnonymousSessionDep
) -> TenantDetail:
    return await _tenant_detail(tenant_id, session)


@router.patch(
    "/tenants/{tenant_id}",
    response_model=TenantDetail,
    summary="Suspend/reactivate a tenant, or change its plan",
)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    session: AnonymousSessionDep,
    admin: PlatformAdminContext = require_platform_role("ADMIN"),
) -> TenantDetail:
    tid = to_uuid(tenant_id)
    row = (
        (
            await session.execute(
                text("SELECT display_name, status, plan FROM tenants WHERE id = :id"),
                {"id": str(tid)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tenant")

    if body.status is not None and body.status != row["status"]:
        await session.execute(
            text("UPDATE tenants SET status = :s WHERE id = :id"),
            {"s": body.status, "id": str(tid)},
        )
        await record_audit(
            session,
            admin,
            "TENANT_SUSPENDED" if body.status == "SUSPENDED" else "TENANT_REACTIVATED",
            "tenant",
            tid,
            row["display_name"],
            {"from": row["status"], "to": body.status},
        )
    if body.plan is not None and body.plan != row["plan"]:
        await session.execute(
            text("UPDATE tenants SET plan = :p WHERE id = :id"), {"p": body.plan, "id": str(tid)}
        )
        await record_audit(
            session,
            admin,
            "TENANT_PLAN_CHANGED",
            "tenant",
            tid,
            row["display_name"],
            {"from": row["plan"], "to": body.plan},
        )

    return await _tenant_detail(tenant_id, session)


@router.post(
    "/tenants/{tenant_id}/archive",
    response_model=TenantDetail,
    summary="Offboard a tenant (soft-delete)",
)
async def archive_tenant(
    tenant_id: str,
    session: AnonymousSessionDep,
    admin: PlatformAdminContext = require_platform_role("ADMIN"),
) -> TenantDetail:
    tid = to_uuid(tenant_id)
    row = (
        (
            await session.execute(
                text("SELECT display_name FROM tenants WHERE id = :id AND archived_at IS NULL"),
                {"id": str(tid)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tenant, or already archived")
    await session.execute(
        text("UPDATE tenants SET archived_at = :now WHERE id = :id"),
        {"now": datetime.now(UTC), "id": str(tid)},
    )
    await record_audit(session, admin, "TENANT_ARCHIVED", "tenant", tid, row["display_name"])
    return await _tenant_detail(tenant_id, session)


@router.post(
    "/tenants/{tenant_id}/restore",
    response_model=TenantDetail,
    summary="Restore an archived tenant",
)
async def restore_tenant(
    tenant_id: str,
    session: AnonymousSessionDep,
    admin: PlatformAdminContext = require_platform_role("ADMIN"),
) -> TenantDetail:
    tid = to_uuid(tenant_id)
    row = (
        (
            await session.execute(
                text("SELECT display_name FROM tenants WHERE id = :id AND archived_at IS NOT NULL"),
                {"id": str(tid)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tenant, or not archived")
    await session.execute(
        text("UPDATE tenants SET archived_at = NULL WHERE id = :id"), {"id": str(tid)}
    )
    await record_audit(session, admin, "TENANT_RESTORED", "tenant", tid, row["display_name"])
    return await _tenant_detail(tenant_id, session)


@router.get("/admins", response_model=list[PlatformAdminSummary], summary="List platform admins")
async def list_admins(
    admin: CurrentPlatformAdminCtx, session: AnonymousSessionDep
) -> list[PlatformAdminSummary]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, name, email, role, status, created_at, last_login_at "
                    "FROM platform_admins ORDER BY name"
                )
            )
        )
        .mappings()
        .all()
    )
    return [
        PlatformAdminSummary(
            id=to_typed_id("user", r["id"]),
            name=r["name"],
            email=r["email"],
            role=r["role"],
            status=r["status"],
            created_at=r["created_at"],
            last_login_at=r["last_login_at"],
            is_you=(r["id"] == admin.admin_id),
        )
        for r in rows
    ]


@router.post(
    "/admins",
    response_model=PlatformAdminSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Add another platform admin",
)
async def create_admin(
    body: PlatformAdminCreate,
    session: AnonymousSessionDep,
    admin: PlatformAdminContext = require_platform_role("ADMIN"),
) -> PlatformAdminSummary:
    existing = (
        await session.execute(
            text("SELECT 1 FROM platform_admins WHERE lower(email) = lower(:email)"),
            {"email": body.email},
        )
    ).first()
    if existing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A platform admin with this email already exists"
        )

    new_id = uuid4()
    await session.execute(
        text("""
            INSERT INTO platform_admins (id, email, name, password_hash, role, status)
            VALUES (:id, :email, :name, :pw, :role, 'ACTIVE')
        """),
        {
            "id": str(new_id),
            "email": body.email,
            "name": body.name,
            "pw": await ahash_password(body.password),
            "role": body.role,
        },
    )
    await record_audit(
        session, admin, "ADMIN_CREATED", "platform_admin", new_id, body.name, {"role": body.role}
    )
    return PlatformAdminSummary(
        id=to_typed_id("user", new_id),
        name=body.name,
        email=body.email,
        role=body.role,
        status="ACTIVE",
        created_at=datetime.now(UTC),
        last_login_at=None,
        is_you=False,
    )


async def _active_admin_role_count(session, exclude_id: UUID) -> int:
    return (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM platform_admins WHERE status = 'ACTIVE' "
                "AND role = 'ADMIN' AND id != :id"
            ),
            {"id": str(exclude_id)},
        )
    ).scalar_one()


@router.patch(
    "/admins/{admin_id}",
    response_model=PlatformAdminSummary,
    summary="Suspend/reactivate a platform admin, or change their role",
)
async def update_admin(
    admin_id: str,
    body: PlatformAdminUpdate,
    session: AnonymousSessionDep,
    admin: PlatformAdminContext = require_platform_role("ADMIN"),
) -> PlatformAdminSummary:
    target_id = to_uuid(admin_id)
    if target_id == admin.admin_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You can't change your own account here — ask another admin",
        )

    row = (
        (
            await session.execute(
                text(
                    "SELECT id, name, email, role, status, created_at, last_login_at "
                    "FROM platform_admins WHERE id = :id"
                ),
                {"id": str(target_id)},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such platform admin")

    losing_admin_power = (body.status == "SUSPENDED" and row["status"] == "ACTIVE") or (
        body.role == "VIEWER" and row["role"] == "ADMIN"
    )
    if (
        losing_admin_power
        and row["role"] == "ADMIN"
        and row["status"] == "ACTIVE"
        and not await _active_admin_role_count(session, target_id)
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Can't remove the platform's last active admin"
        )

    new_status, new_role = row["status"], row["role"]
    if body.status is not None and body.status != row["status"]:
        await session.execute(
            text(
                "UPDATE platform_admins SET status = :s, "
                "token_epoch = token_epoch + 1 WHERE id = :id"
            ),
            {"s": body.status, "id": str(target_id)},
        )
        await record_audit(
            session,
            admin,
            "ADMIN_SUSPENDED" if body.status == "SUSPENDED" else "ADMIN_REACTIVATED",
            "platform_admin",
            target_id,
            row["name"],
        )
        new_status = body.status
    if body.role is not None and body.role != row["role"]:
        await session.execute(
            text("UPDATE platform_admins SET role = :r WHERE id = :id"),
            {"r": body.role, "id": str(target_id)},
        )
        await record_audit(
            session,
            admin,
            "ADMIN_ROLE_CHANGED",
            "platform_admin",
            target_id,
            row["name"],
            {"from": row["role"], "to": body.role},
        )
        new_role = body.role

    return PlatformAdminSummary(
        id=to_typed_id("user", target_id),
        name=row["name"],
        email=row["email"],
        role=new_role,
        status=new_status,
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
        is_you=False,
    )


@router.get(
    "/audit-log",
    response_model=AuditLogResponse,
    summary="Every mutating platform action, most recent first",
)
async def get_audit_log(
    _admin: CurrentPlatformAdminCtx, session: AnonymousSessionDep, limit: int = 50, offset: int = 0
) -> AuditLogResponse:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = (
        (
            await session.execute(
                text("""
                SELECT id, actor_name, action, target_type, target_id, target_label,
                metadata_json, created_at
                FROM platform_audit_log ORDER BY created_at DESC LIMIT :limit OFFSET :offset
            """),
                {"limit": limit, "offset": offset},
            )
        )
        .mappings()
        .all()
    )
    total = (await session.execute(text("SELECT COUNT(*) FROM platform_audit_log"))).scalar_one()
    return AuditLogResponse(
        total=total,
        items=[
            AuditLogEntry(
                id=to_typed_id("audit", r["id"]),
                actor_name=r["actor_name"],
                action=r["action"],
                target_type=r["target_type"],
                target_id=str(r["target_id"]) if r["target_id"] else None,
                target_label=r["target_label"],
                metadata=r["metadata_json"],
                created_at=r["created_at"],
            )
            for r in rows
        ],
    )


@router.post(
    "/companies",
    response_model=PlatformCompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a company — as its own new tenant, or as a subsidiary of an existing one",
)
async def create_company(
    body: PlatformCompanyCreate,
    session: AnonymousSessionDep,
    admin: PlatformAdminContext = require_platform_role("ADMIN"),
) -> PlatformCompanyResponse:
    if body.mode == "NEW_TENANT":
        if not body.admin_email or not body.admin_password:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "admin_email and admin_password are required for a new tenant",
            )
        tenant_id, legal_entity_id, _account_id = await bootstrap_tenant(
            session,
            company_name=body.company_name,
            country_code=body.country_code,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
        )
        await record_audit(
            session,
            admin,
            "TENANT_CREATED",
            "tenant",
            tenant_id,
            body.company_name,
            {"mode": "NEW_TENANT"},
        )
        return PlatformCompanyResponse(
            mode="NEW_TENANT",
            tenant_id=to_typed_id("tenant", tenant_id),
            tenant_name=body.company_name,
            legal_entity_id=to_typed_id("legal_entity", legal_entity_id),
            legal_entity_name=body.company_name,
            admin_email=body.admin_email,
        )

    # SUBSIDIARY — link into an EXISTING tenant as another legal entity.
    if not body.parent_tenant_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "parent_tenant_id is required to link as a subsidiary"
        )
    parent_tenant_id = to_uuid(body.parent_tenant_id)

    tenant_row = (
        (
            await session.execute(
                text("SELECT display_name FROM tenants WHERE id = :id"),
                {"id": str(parent_tenant_id)},
            )
        )
        .mappings()
        .first()
    )
    if not tenant_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tenant")

    # Bind this session to the PARENT tenant so the RLS WITH CHECK on
    # legal_entities passes — same set_config mechanism bootstrap_tenant
    # uses for a brand-new tenant, just pointed at one that already exists.
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(parent_tenant_id)}
    )

    legal_entity_id = uuid4()
    session.add(
        LegalEntity(
            tenant_id=parent_tenant_id,
            id=legal_entity_id,
            name=body.company_name,
            country_code=body.country_code,
        )
    )
    await session.flush()
    await record_audit(
        session,
        admin,
        "TENANT_CREATED",
        "legal_entity",
        legal_entity_id,
        body.company_name,
        {"mode": "SUBSIDIARY", "parent_tenant": tenant_row["display_name"]},
    )

    return PlatformCompanyResponse(
        mode="SUBSIDIARY",
        tenant_id=to_typed_id("tenant", parent_tenant_id),
        tenant_name=tenant_row["display_name"],
        legal_entity_id=to_typed_id("legal_entity", legal_entity_id),
        legal_entity_name=body.company_name,
        admin_email=None,
    )

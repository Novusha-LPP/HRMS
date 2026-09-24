"""
Shared logic for standing up a brand-new tenant — used by both the public
self-serve POST /v1/auth/register-company and the platform admin's
POST /v1/platform/companies (mode=NEW_TENANT). Keeping this in one place
means there is exactly one code path that can create a tenant, so the
"roles bootstrapped, first legal entity created, admin account valid"
invariant can't drift between the two callers.
"""

import re
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.authz import ROLE_DESCRIPTIONS
from hrms.core.security import hash_password
from hrms.modules.kernel.models import Role, RoleAssignment, Tenant, UserAccount
from hrms.modules.org.models import LegalEntity


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "company")[:40]


async def bootstrap_tenant(
    session: AsyncSession, *, company_name: str, country_code: str, admin_email: str, admin_password: str,
) -> tuple[UUID, UUID, UUID]:
    """
    Runs on a session with no tenant bound yet (AnonymousSessionDep, or the
    platform router's bare session) — there is no existing tenant to have
    bound it to. Returns (tenant_id, legal_entity_id, admin_account_id).

    Email must be globally unique across every tenant, since login_lookup()
    resolves tenant purely from email with no other hint — checked through
    that same SECURITY DEFINER function rather than a plain SELECT, which
    RLS would silently scope to nothing on an unbound session.
    """
    existing = (
        await session.execute(text("SELECT 1 FROM login_lookup(:email)"), {"email": admin_email})
    ).first()
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An account with this email already exists")

    slug = slugify(company_name)
    for candidate in (slug, f"{slug}-{uuid4().hex[:6]}"):
        taken = (await session.execute(text("SELECT 1 FROM tenants WHERE slug = :slug"), {"slug": candidate})).first()
        if not taken:
            slug = candidate
            break
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not allocate a unique identifier — try again")

    tenant_id = uuid4()
    # Bind this session to the tenant we're about to create. RLS only checks
    # equality against tenant_id, so this is fine even before the tenants
    # row exists — every insert below just needs to carry the same value.
    await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})

    tenant = Tenant(id=tenant_id, slug=slug, display_name=company_name, country_code=country_code)
    session.add(tenant)
    await session.flush()  # tenants has no RLS, but children FK-reference it — must exist first

    role_ids: dict[str, UUID] = {}
    for name, desc in ROLE_DESCRIPTIONS.items():
        role_id = uuid4()
        role_ids[name] = role_id
        session.add(Role(tenant_id=tenant_id, id=role_id, name=name, description=desc, is_system=True))

    legal_entity_id = uuid4()
    session.add(LegalEntity(tenant_id=tenant_id, id=legal_entity_id, name=company_name, country_code=country_code))
    await session.flush()

    account_id = uuid4()
    session.add(UserAccount(
        tenant_id=tenant_id, id=account_id, email=admin_email,
        password_hash=hash_password(admin_password), status="ACTIVE",
    ))
    await session.flush()

    session.add(RoleAssignment(
        tenant_id=tenant_id, id=uuid4(), user_account_id=account_id,
        role_id=role_ids["SUPER_ADMIN"], scope_type="ALL",
    ))
    await session.flush()

    return tenant_id, legal_entity_id, account_id

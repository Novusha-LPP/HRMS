"""
User accounts & role assignments — /v1/users, /v1/roles.

This is how a company (or the whole tenant) gets its first login after
onboarding: POST /v1/legal-entities creates the company, then POST
/v1/users creates a login and grants it a role scoped to that company. Until
this module existed, the ONLY way to create a user_accounts row was the
seed script's raw SQL — there was no runtime path at all, so a freshly
onboarded company had no way to get anyone signed in.

Two escalation guards, since granting a login is granting authority:
  - scope guard: the requested scope_type/legal_entity_ids/employment_id
    must be inside what the CALLER can already see (same rule org.write
    uses for locations/org-units — scope.covers_entity / authorize_employment).
  - permission guard: the target role's permission bundle must be a subset
    of the caller's own permissions, so an HR_MANAGER (no "*") can't mint a
    SUPER_ADMIN account for themselves or anyone else.
"""

import json
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from hrms.core.authz import (
    ROLE_PERMISSIONS,
    ScopeDep,
    authorize_employment,
    decode_scope_ids,
    require_permission,
)
from hrms.core.database import SessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.security import hash_password
from hrms.core.tenancy import TenantDep
from hrms.modules.kernel.models import RoleAssignment, UserAccount
from hrms.modules.kernel.users.schemas import RoleResponse, UserCreate, UserResponse

router = APIRouter(tags=["Users"])


@router.get(
    "/v1/roles", response_model=list[RoleResponse], summary="List roles available in this tenant"
)
async def list_roles(tenant_id: TenantDep, session: SessionDep) -> list[RoleResponse]:
    rows = await session.execute(
        text(
            "SELECT name, description FROM roles WHERE tenant_id = CAST(:tid AS uuid) ORDER BY name"
        ),
        {"tid": str(tenant_id)},
    )
    return [
        RoleResponse(
            name=r["name"],
            description=r["description"],
            permissions=sorted(ROLE_PERMISSIONS.get(r["name"], frozenset())),
        )
        for r in rows.mappings()
    ]


_USER_SELECT = """
    SELECT
        ua.id AS account_id, ua.email, ua.status, ua.employment_id,
        ua.created_at, ua.last_login_at,
        r.name AS role_name,
        ra.scope_type, ra.scope_value,
        e.legal_entity_id AS employment_legal_entity_id,
        p.legal_first_name, p.legal_last_name
    FROM user_accounts ua
    JOIN role_assignments ra ON ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
    JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
    LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
    LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
    WHERE ua.tenant_id = CAST(:tid AS uuid)
    ORDER BY ua.email, r.name
"""


def _user_row_response(r) -> UserResponse:
    legal_entity_ids = [to_typed_id("legal_entity", i) for i in decode_scope_ids(r["scope_value"])]
    name = f"{r['legal_first_name']} {r['legal_last_name']}" if r["legal_first_name"] else None
    return UserResponse(
        id=to_typed_id("user", r["account_id"]),
        email=r["email"],
        status=r["status"],
        role=r["role_name"],
        scope_type=r["scope_type"],
        legal_entity_ids=legal_entity_ids,
        employment_id=to_typed_id("employment", r["employment_id"]) if r["employment_id"] else None,
        employee_name=name,
        created_at=r["created_at"],
        last_login_at=r["last_login_at"],
    )


@router.get(
    "/v1/users",
    response_model=list[UserResponse],
    summary="List user accounts and their access",
    dependencies=[require_permission("iam.read")],
)
async def list_users(
    tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> list[UserResponse]:
    scope = scope.for_permission("iam.read")
    rows = (await session.execute(text(_USER_SELECT), {"tid": str(tenant_id)})).mappings().all()
    if scope.is_all:
        return [_user_row_response(r) for r in rows]

    out: list[UserResponse] = []
    for r in rows:
        if r["scope_type"] == "ALL":
            continue  # a company-scoped viewer can't see who has group-wide access
        if r["scope_type"] == "LEGAL_ENTITY":
            if decode_scope_ids(r["scope_value"]) & scope.legal_entity_ids:
                out.append(_user_row_response(r))
        elif (
            r["scope_type"] in ("SELF", "DIRECT_REPORTS", "ALL_REPORTS")
            and r["employment_legal_entity_id"] in scope.legal_entity_ids
        ):
            out.append(_user_row_response(r))
    return out


@router.post(
    "/v1/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user account and grant it a role",
    dependencies=[require_permission("iam.write")],
)
async def create_user(
    body: UserCreate,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> UserResponse:
    scope = scope.for_permission("iam.write")
    role_row = (
        (
            await session.execute(
                text("SELECT id FROM roles WHERE tenant_id = CAST(:tid AS uuid) AND name = :name"),
                {"tid": str(tenant_id), "name": body.role},
            )
        )
        .mappings()
        .first()
    )
    if not role_row:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown role: {body.role}")

    target_permissions = ROLE_PERMISSIONS.get(body.role, frozenset())
    if not scope.has("*") and not target_permissions.issubset(scope.permissions):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can't grant a role with more permissions than you hold",
        )

    # employment_id is independent of scope_type: it's "which employee this
    # login IS" (drives self-service), separate from what the role grants
    # visibility into. Authorize it up front whenever it's given.
    employment_uuid: UUID | None = None
    if body.employment_id:
        employment_uuid = to_uuid(body.employment_id)
        await authorize_employment(session, tenant_id, scope, employment_uuid)

    legal_entity_uuids: list[UUID] = []
    if body.scope_type == "ALL":
        if not scope.is_all:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only a group-level administrator can grant all-company access",
            )
    elif body.scope_type == "LEGAL_ENTITY":
        if not body.legal_entity_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "legal_entity_ids is required for LEGAL_ENTITY scope"
            )
        legal_entity_uuids = [to_uuid(i) for i in body.legal_entity_ids]
        for eid in legal_entity_uuids:
            if not scope.covers_entity(eid):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Not authorized for one of the given companies"
                )
    elif not body.employment_id:  # SELF, DIRECT_REPORTS, ALL_REPORTS
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"employment_id is required for {body.scope_type} scope"
        )

    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM user_accounts WHERE tenant_id = CAST(:tid AS uuid) "
                "AND lower(email) = lower(:email)"
            ),
            {"tid": str(tenant_id), "email": body.email},
        )
    ).first()
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A user with this email already exists")

    account_id = uuid4()
    account = UserAccount(
        tenant_id=tenant_id,
        id=account_id,
        email=body.email,
        password_hash=hash_password(body.password),
        employment_id=employment_uuid,
        status="ACTIVE",
    )
    session.add(account)

    assignment = RoleAssignment(
        tenant_id=tenant_id,
        id=uuid4(),
        user_account_id=account_id,
        role_id=role_row["id"],
        scope_type=body.scope_type,
        scope_value=(
            json.dumps([to_typed_id("legal_entity", i) for i in legal_entity_uuids])
            if legal_entity_uuids
            else None
        ),
    )
    session.add(assignment)
    await session.flush()

    name = None
    if employment_uuid:
        person_row = (
            (
                await session.execute(
                    text("""
                    SELECT p.legal_first_name, p.legal_last_name
                    FROM employments e JOIN persons p ON p.tenant_id = e.tenant_id AND p.id =
                    e.person_id
                    WHERE e.tenant_id = CAST(:tid AS uuid) AND e.id = CAST(:eid AS uuid)
                """),
                    {"tid": str(tenant_id), "eid": str(employment_uuid)},
                )
            )
            .mappings()
            .first()
        )
        if person_row:
            name = f"{person_row['legal_first_name']} {person_row['legal_last_name']}"

    return UserResponse(
        id=to_typed_id("user", account_id),
        email=account.email,
        status=account.status,
        role=body.role,
        scope_type=body.scope_type,
        legal_entity_ids=[to_typed_id("legal_entity", i) for i in legal_entity_uuids],
        employment_id=to_typed_id("employment", employment_uuid) if employment_uuid else None,
        employee_name=name,
        created_at=account.created_at,
        last_login_at=None,
    )

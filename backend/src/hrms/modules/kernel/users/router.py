"""
User accounts & role assignments — /v1/users, /v1/roles.

This is how a company (or the whole tenant) gets its first login after
onboarding: POST /v1/legal-entities creates the company, then POST
/v1/users creates a login and grants it a role scoped to that company. Until
this module existed, the ONLY way to create a user_accounts row was the
seed script's raw SQL — there was no runtime path at all, so a freshly
onboarded company had no way to get anyone signed in.

Managing an existing login:
  PATCH /v1/users/{id}                 — ACTIVE / INACTIVE. INACTIVE locks the
                                          person out at once, tokens included.
  POST  /v1/users/{id}/reset-password  — set a temporary password; the person
                                          must replace it at next sign-in and
                                          every session they had is ended.
(A separated employee is locked out automatically — see core/database.get_session
— so INACTIVE is for everything else: a suspended contractor, a shared login
that should stop, an account created by mistake.)

Escalation guards, since granting or managing a login is granting authority:
  - scope guard: the requested scope_type/legal_entity_ids/employment_id
    must be inside what the CALLER can already see (same rule org.write
    uses for locations/org-units — scope.covers_entity / authorize_employment).
  - permission guard: the target role's permission bundle must be a subset
    of the caller's own permissions, so an HR_MANAGER (no "*") can't mint a
    SUPER_ADMIN account for themselves or anyone else — nor disable or take
    over one that already exists.
  - role/scope guard: EMPLOYEE is a self-service-only role, so it can only be
    granted with SELF scope. Read endpoints filter by the union of a user's
    scopes, so an EMPLOYEE login with a company-wide scope would be able to
    read the whole company's records.
"""

import asyncio
import json
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    ROLE_PERMISSIONS,
    Scope,
    ScopeDep,
    authorize_employment,
    decode_scope_ids,
    require_permission,
)
from hrms.core.change_audit import record_change
from hrms.core.database import SessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.security import ahash_password
from hrms.core.tenancy import TenantDep
from hrms.modules.kernel.models import RoleAssignment, UserAccount
from hrms.modules.kernel.users.schemas import (
    PasswordReset,
    RoleResponse,
    SignInSlip,
    SignInSlipsRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)

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


def _user_select(*, role_join: str = "JOIN", extra_where: str = "") -> str:
    return f"""
    SELECT
        ua.id AS account_id, ua.email, ua.status, ua.employment_id,
        ua.created_at, ua.last_login_at, ua.must_change_password,
        r.name AS role_name,
        ra.scope_type, ra.scope_value,
        e.legal_entity_id AS employment_legal_entity_id, e.employment_state,
        p.legal_first_name, p.legal_last_name
    FROM user_accounts ua
    {role_join} role_assignments ra
        ON ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
    {role_join} roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
    LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
    LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
    WHERE ua.tenant_id = CAST(:tid AS uuid) {extra_where}
    ORDER BY ua.email, r.name, ua.id, ra.id
"""


def _user_row_response(r) -> UserResponse:
    legal_entity_ids = [to_typed_id("legal_entity", i) for i in decode_scope_ids(r["scope_value"])]
    name = f"{r['legal_first_name']} {r['legal_last_name']}" if r["legal_first_name"] else None
    return UserResponse(
        id=to_typed_id("user", r["account_id"]),
        email=r["email"],
        status=r["status"],
        role=r["role_name"] or "",
        scope_type=r["scope_type"] or "",
        legal_entity_ids=legal_entity_ids,
        employment_id=to_typed_id("employment", r["employment_id"]) if r["employment_id"] else None,
        employee_name=name,
        created_at=r["created_at"],
        last_login_at=r["last_login_at"],
        employment_state=r["employment_state"],
        can_sign_in=r["status"] == "ACTIVE" and r["employment_state"] != "SEPARATED",
        must_change_password=bool(r["must_change_password"]),
    )


@router.get(
    "/v1/users",
    response_model=list[UserResponse],
    summary="List user accounts and their access",
    dependencies=[require_permission("iam.read")],
)
async def list_users(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> list[UserResponse]:
    scope = scope.for_permission("iam.read")
    where = ""
    params: dict = {"tid": str(tenant_id), "limit": limit, "offset": offset}
    if not scope.is_all:
        # Old imports may contain malformed JSON. Parse only valid arrays, and
        # apply visibility BEFORE LIMIT so sparse company scopes paginate correctly.
        parsed = (
            "CASE WHEN pg_input_is_valid(ra.scope_value,'jsonb') "
            "THEN CAST(ra.scope_value AS jsonb) ELSE '[]'::jsonb END"
        )
        array = f"CASE WHEN jsonb_typeof({parsed})='array' THEN {parsed} ELSE '[]'::jsonb END"
        where = f"""AND ((ra.scope_type='LEGAL_ENTITY' AND
            ({array}) ?| CAST(:entity_tokens AS text[])) OR
            (ra.scope_type IN ('SELF','DIRECT_REPORTS','ALL_REPORTS') AND
             e.legal_entity_id = ANY(CAST(:entity_ids AS uuid[]))))"""
        params["entity_ids"] = list(scope.legal_entity_ids)
        params["entity_tokens"] = [
            token
            for eid in scope.legal_entity_ids
            for token in (str(eid), to_typed_id("legal_entity", eid))
        ]
    rows = (
        await session.execute(
            text(_user_select(extra_where=where) + " LIMIT :limit OFFSET :offset"), params
        )
    ).mappings()
    return [_user_row_response(row) for row in rows]


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

    if body.role == "EMPLOYEE" and body.scope_type != "SELF":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "EMPLOYEE is a self-service role and can only be granted with SELF scope",
        )

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
        password_hash=await ahash_password(body.password),
        employment_id=employment_uuid,
        status="ACTIVE",
        must_change_password=body.must_change_password,
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

    rows = await _fetch_user_rows(session, tenant_id, account_id)
    return _user_row_response(rows[0])


# ─── Managing an existing login ──────────────────────────────────────────────


async def _fetch_user_rows(session, tenant_id: UUID, account_id: UUID):
    rows = (
        (
            await session.execute(
                text(
                    _user_select(
                        role_join="LEFT JOIN", extra_where="AND ua.id = CAST(:uid AS uuid)"
                    )
                ),
                {"tid": str(tenant_id), "uid": str(account_id)},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return rows


async def _load_manageable_account(
    session, tenant_id: UUID, principal, scope: Scope, user_id: str
) -> tuple[UUID, set[str]]:
    """
    Resolve the target login and refuse anything the caller isn't entitled to
    manage: themselves (use change-password), accounts holding more authority
    than the caller, group-wide accounts unless the caller is group-wide, and
    employees outside the caller's scope.
    """
    account_id = to_uuid(user_id)
    account = (
        (
            await session.execute(
                text("""
                    SELECT id, employment_id FROM user_accounts
                    WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)
                """),
                {"tid": str(tenant_id), "uid": str(account_id)},
            )
        )
        .mappings()
        .first()
    )
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if account_id == principal.user_account_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You can't change your own account here — use change-password instead",
        )

    grants = (
        (
            await session.execute(
                text("""
                    SELECT r.name AS role_name, ra.scope_type
                    FROM role_assignments ra
                    JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                    WHERE ra.tenant_id = CAST(:tid AS uuid)
                      AND ra.user_account_id = CAST(:uid AS uuid)
                """),
                {"tid": str(tenant_id), "uid": str(account_id)},
            )
        )
        .mappings()
        .all()
    )
    role_names = {g["role_name"] for g in grants}
    target_permissions: set[str] = set()
    for name in role_names:
        target_permissions |= ROLE_PERMISSIONS.get(name, frozenset())
    if not scope.has("*") and not target_permissions <= set(scope.permissions):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can't manage an account that holds more permissions than you do",
        )
    if any(g["scope_type"] == "ALL" for g in grants) and not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can manage an account with all-company access",
        )
    if account["employment_id"]:
        await authorize_employment(session, tenant_id, scope, account["employment_id"])
    elif not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can manage an account with no employee record",
        )
    return account_id, role_names


@router.patch(
    "/v1/users/{user_id}",
    response_model=UserResponse,
    summary="Activate or deactivate a login",
    dependencies=[require_permission("iam.write")],
)
async def update_user(
    user_id: str,
    body: UserUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> UserResponse:
    scope = scope.for_permission("iam.write")
    account_id, role_names = await _load_manageable_account(
        session, tenant_id, principal, scope, user_id
    )

    if body.status == "INACTIVE" and "SUPER_ADMIN" in role_names:
        other_admins = (
            await session.execute(
                text("""
                    SELECT count(*) FROM user_accounts ua
                    JOIN role_assignments ra
                      ON ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
                    JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                    WHERE ua.tenant_id = CAST(:tid AS uuid) AND ua.status = 'ACTIVE'
                      AND r.name = 'SUPER_ADMIN' AND ua.id <> CAST(:uid AS uuid)
                """),
                {"tid": str(tenant_id), "uid": str(account_id)},
            )
        ).scalar()
        if not other_admins:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This is the last active administrator — make another one first",
            )

    await session.execute(
        text("""
            UPDATE user_accounts SET status = :status, version = version + 1
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)
        """),
        {"status": body.status, "tid": str(tenant_id), "uid": str(account_id)},
    )
    return _user_row_response((await _fetch_user_rows(session, tenant_id, account_id))[0])


@router.post(
    "/v1/users/{user_id}/reset-password",
    response_model=UserResponse,
    summary="Set a temporary password the user must replace at next sign-in",
    dependencies=[require_permission("iam.write")],
)
async def reset_user_password(
    user_id: str,
    body: PasswordReset,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> UserResponse:
    scope = scope.for_permission("iam.write")
    account_id, _ = await _load_manageable_account(session, tenant_id, principal, scope, user_id)

    new_hash = await ahash_password(body.password)
    await session.execute(
        text("""
            UPDATE user_accounts
            SET password_hash = :hash, must_change_password = true,
                password_changed_at = :changed_at, token_epoch = token_epoch + 1,
                version = version + 1
            WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)
        """),
        {
            "hash": new_hash,
            "changed_at": datetime.now(UTC),
            "tid": str(tenant_id),
            "uid": str(account_id),
        },
    )
    return _user_row_response((await _fetch_user_rows(session, tenant_id, account_id))[0])


# ─── Sign-in slips for staff without email ───────────────────────────────────

_UNAMBIGUOUS = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


def _temporary_password(numeric: bool) -> str:
    if numeric:
        return "".join(secrets.choice("0123456789") for _ in range(8))
    return "".join(secrets.choice(_UNAMBIGUOUS) for _ in range(10))


@router.post(
    "/v1/users/sign-in-slips",
    response_model=list[SignInSlip],
    summary="Issue temporary sign-in details to employees",
    dependencies=[require_permission("iam.write")],
)
async def issue_sign_in_slips(
    body: SignInSlipsRequest,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> list[SignInSlip]:
    """
    For each employee: an employee login (role EMPLOYEE, own record only) is created if
    there is none, or the existing one gets a new temporary password. Either way they sign
    in with their employee number and must choose their own password first. Logins that
    hold more than self-service (HR, managers, admins), switched-off logins, people who
    have left and the caller's own login are skipped, with the reason.
    """
    scope = scope.for_permission("iam.write")
    requested = list(dict.fromkeys(body.employment_ids))
    uuids = {typed: to_uuid(typed) for typed in requested}

    role_id = (
        await session.execute(
            text("SELECT id FROM roles WHERE tenant_id = CAST(:tid AS uuid) AND name = 'EMPLOYEE'"),
            {"tid": str(tenant_id)},
        )
    ).scalar()
    if role_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This company has no EMPLOYEE role")

    rows = (
        await session.execute(
            text("""
                SELECT e.id, e.employee_number, e.employment_state, le.name AS company,
                       COALESCE(NULLIF(p.preferred_name, ''), p.legal_first_name)
                           || ' ' || p.legal_last_name AS name,
                       (SELECT array_agg(ua.id) FROM user_accounts ua
                        WHERE ua.tenant_id = e.tenant_id AND ua.employment_id = e.id) AS accounts
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                WHERE e.tenant_id = CAST(:tid AS uuid) AND e.id = ANY(CAST(:ids AS uuid[]))
            """),
            {"tid": str(tenant_id), "ids": [str(u) for u in uuids.values()]},
        )
    ).mappings()
    by_id = {r["id"]: r for r in rows}

    results: dict[str, SignInSlip] = {}
    plans: list[tuple[str, UUID | None]] = []  # (typed employment id, account to reset or None)
    for typed, uid in uuids.items():
        row = by_id.get(uid)

        def skip(reason: str, row=row, typed=typed) -> None:
            results[typed] = SignInSlip(
                employment_id=typed,
                employee_number=row["employee_number"] if row else "",
                name=row["name"] if row else "",
                company=row["company"] if row else None,
                outcome="SKIPPED",
                reason=reason,
            )

        if row is None:
            skip("Employee not found")
            continue
        try:
            await authorize_employment(session, tenant_id, scope, uid)
        except HTTPException:
            skip("Outside the companies you manage")
            continue
        if row["employment_state"] == "SEPARATED":
            skip("Has left")
            continue
        if principal.employment_id == uid:
            skip("Your own login: use change password instead")
            continue
        accounts = row["accounts"] or []
        if len(accounts) > 1:
            skip("Has more than one login: reset the right one on its own")
            continue
        if accounts:
            account = (
                (
                    await session.execute(
                        text("""
                        SELECT ua.status,
                               array_agg(r.name) FILTER (WHERE r.name IS NOT NULL) AS roles
                        FROM user_accounts ua
                        LEFT JOIN role_assignments ra
                          ON ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
                        LEFT JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                        WHERE ua.tenant_id = CAST(:tid AS uuid) AND ua.id = CAST(:uid AS uuid)
                        GROUP BY ua.status
                    """),
                        {"tid": str(tenant_id), "uid": str(accounts[0])},
                    )
                )
                .mappings()
                .first()
            )
            if account["status"] != "ACTIVE":
                skip("Login is switched off")
                continue
            if set(account["roles"] or []) - {"EMPLOYEE"}:
                skip("Has an HR, manager or admin login: reset it on its own")
                continue
        plans.append((typed, accounts[0] if accounts else None))

    passwords = {typed: _temporary_password(body.numeric) for typed, _ in plans}
    hashes = dict(
        zip(
            [typed for typed, _ in plans],
            await asyncio.gather(*(ahash_password(passwords[typed]) for typed, _ in plans)),
            strict=True,
        )
    )
    now = datetime.now(UTC)
    for typed, account_id in plans:
        row = by_id[uuids[typed]]
        if account_id is None:
            account_id = uuid4()
            session.add(
                UserAccount(
                    tenant_id=tenant_id,
                    id=account_id,
                    password_hash=hashes[typed],
                    employment_id=uuids[typed],
                    status="ACTIVE",
                    must_change_password=True,
                    password_changed_at=now,
                )
            )
            session.add(
                RoleAssignment(
                    tenant_id=tenant_id,
                    id=uuid4(),
                    user_account_id=account_id,
                    role_id=role_id,
                    scope_type="SELF",
                )
            )
            outcome = "CREATED"
        else:
            await session.execute(
                text("""
                    UPDATE user_accounts
                    SET password_hash = :hash, must_change_password = true,
                        password_changed_at = :changed_at, token_epoch = token_epoch + 1,
                        version = version + 1
                    WHERE tenant_id = CAST(:tid AS uuid) AND id = CAST(:uid AS uuid)
                """),
                {
                    "hash": hashes[typed],
                    "changed_at": now,
                    "tid": str(tenant_id),
                    "uid": str(account_id),
                },
            )
            outcome = "RESET"
        await session.flush()
        await record_change(
            session,
            tenant_id,
            "user_account",
            account_id,
            "CREATE" if outcome == "CREATED" else "UPDATE",
            changed_by=principal.user_account_id,
            before=None if outcome == "CREATED" else {"temporary_password": None},
            after={"temporary_password": "issued on a sign-in slip"},
        )
        results[typed] = SignInSlip(
            employment_id=typed,
            employee_number=row["employee_number"],
            name=row["name"],
            company=row["company"],
            outcome=outcome,
            temporary_password=passwords[typed],
        )
    return [results[typed] for typed in requested]

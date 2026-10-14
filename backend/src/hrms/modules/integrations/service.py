"""
Employee sync: what /v1/integrations/employees/* does (plan §7).

Every operation runs inside the request's transaction, behind a transaction-level advisory lock
on (tenant, app, external_id), so two concurrent calls for one person run one after the other.
Lifecycle changes go through the same personnel-action code HR uses, so history, effective dates
and the scheduler behave exactly as they do for changes made in HRMS.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import select

from hrms.core.datetime_utils import business_today
from hrms.core.errors import CodedHTTPException
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.security import ahash_password
from hrms.modules.integrations.catalog import IntegrationSettings, password_from_pattern
from hrms.modules.integrations.events import reschedule_held_hire
from hrms.modules.integrations.keys import IntegrationContext
from hrms.modules.integrations.profiles import effective_settings
from hrms.modules.integrations.schemas import EmployeeUpsert, ExitRequest, RehireRequest, SyncResult
from hrms.modules.kernel.models import RoleAssignment, UserAccount
from hrms.modules.people.models import (
    Employment,
    EmploymentState,
    Person,
    PersonnelAction,
    PersonnelActionStatus,
    PersonnelActionType,
)

BCRYPT_HASH = re.compile(r"^\$2[aby]\$1[0-4]\$[./A-Za-z0-9]{53}$")

# Payload fields -> catalogue fields (for ownership).
PAYLOAD_FIELDS = {
    "employee_code": "employee_code",
    "first_name": "first_name",
    "last_name": "last_name",
    "preferred_name": "preferred_name",
    "email": "email",
    "mobile": "mobile",
    "date_of_birth": "date_of_birth",
    "gender": "gender",
    "company": "company",
    "department": "department",
    "location": "location",
    "designation": "designation",
    "manager_external_id": "manager",
    "role": "role",
    "hire_date": "hire_date",
}
JOB_FIELDS = ("department", "location", "designation", "manager_external_id")


class SyncError(CodedHTTPException):
    """A refusal that is logged with its detail (e.g. which value is unmapped)."""

    def __init__(self, status_code: int, message: str, code: str, detail: dict | None = None):
        super().__init__(status_code, message, code=code)
        self.sync_detail = detail or {}


# ─── Look-ups ────────────────────────────────────────────────────────────────


async def lock_external(ctx: IntegrationContext, external_id: str) -> None:
    await lock_resource(ctx.session, ctx.tenant_id, f"integration:{ctx.app_id}:{external_id}")


async def find_identity(ctx: IntegrationContext, external_id: str) -> dict[str, Any] | None:
    row = (
        (
            await ctx.session.execute(
                text("""
                SELECT x.*, e.legal_entity_id, e.employment_state
                FROM external_identities x
                JOIN employments e ON e.tenant_id = x.tenant_id AND e.id = x.employment_id
                WHERE x.tenant_id = :tid AND x.app_id = :app AND x.external_id = :ext
            """),
                {"tid": ctx.tenant_id, "app": ctx.app_id, "ext": external_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def settings_for(
    ctx: IntegrationContext, legal_entity_id: UUID | None
) -> IntegrationSettings:
    return await effective_settings(ctx.session, ctx.tenant_id, ctx.app_id, legal_entity_id)


_KIND_LABEL = {
    "LEGAL_ENTITY": "company",
    "DEPARTMENT": "department",
    "LOCATION": "location",
    "DESIGNATION": "designation",
}


async def resolve(
    ctx: IntegrationContext,
    kind: str,
    value: str,
    *,
    legal_entity_id: UUID | None,
    settings: IntegrationSettings | None,
) -> UUID:
    """An app's value -> an HRMS id: mapping first, then exact code, then exact name."""
    session = ctx.session
    mapped = (
        await session.execute(
            text("""
            SELECT target_id FROM integration_mappings
            WHERE tenant_id = :tid AND app_id = :app AND kind = :kind
              AND lower(external_value) = lower(:v)
        """),
            {"tid": ctx.tenant_id, "app": ctx.app_id, "kind": kind, "v": value.strip()},
        )
    ).scalar()
    if mapped:
        if kind in ("DEPARTMENT", "LOCATION") and legal_entity_id is not None:
            table = "org_units" if kind == "DEPARTMENT" else "locations"
            owner = (
                await session.execute(
                    text(
                        f"SELECT legal_entity_id FROM {table} WHERE tenant_id = :tid AND id = :id"
                    ),
                    {"tid": ctx.tenant_id, "id": mapped},
                )
            ).first()
            # A department belongs to one company; a location may be shared (no company).
            if owner is None or (
                owner[0] != legal_entity_id and not (kind == "LOCATION" and owner[0] is None)
            ):
                raise SyncError(
                    422,
                    f"'{value.strip()}' is mapped to a {_KIND_LABEL[kind]} of another company.",
                    f"MAPPING_OTHER_COMPANY_{kind}",
                    {"kind": kind, "value": value.strip()},
                )
        return mapped
    v = value.strip()
    if kind == "LEGAL_ENTITY":
        sql = """SELECT id FROM legal_entities WHERE tenant_id = :tid AND archived_at IS NULL
                 AND (lower(short_name) = lower(:v) OR lower(name) = lower(:v))"""
    elif kind == "DEPARTMENT":
        sql = """SELECT id FROM org_units WHERE tenant_id = :tid AND archived_at IS NULL
                 AND type <> 'DEPARTMENT_TEMPLATE' AND legal_entity_id = :le
                 AND (lower(code) = lower(:v) OR lower(name) = lower(:v))"""
    elif kind == "LOCATION":
        sql = """SELECT id FROM locations WHERE tenant_id = :tid
                 AND (legal_entity_id = :le OR legal_entity_id IS NULL)
                 AND lower(name) = lower(:v)"""
    else:
        sql = """SELECT id FROM jobs WHERE tenant_id = :tid AND archived_at IS NULL
                 AND (lower(code) = lower(:v) OR lower(title) = lower(:v))"""
    ids = (
        (await session.execute(text(sql), {"tid": ctx.tenant_id, "v": v, "le": legal_entity_id}))
        .scalars()
        .all()
    )
    if len(ids) == 1:
        return ids[0]
    label = _KIND_LABEL[kind]
    if len(ids) > 1:
        raise SyncError(
            422,
            f"More than one {label} in HRMS matches '{v}'. Map the value on the Mappings tab.",
            f"AMBIGUOUS_{kind}",
            {"kind": kind, "value": v},
        )
    if settings is not None and settings.unknown_values == "CREATE" and kind != "LEGAL_ENTITY":
        return await _create_reference(ctx, kind, v, legal_entity_id)
    raise SyncError(
        422,
        f"HRMS has no {label} '{v}'. Map it on the Mappings tab, then retry.",
        f"UNKNOWN_{kind}",
        {"kind": kind, "value": v},
    )


async def _create_reference(
    ctx: IntegrationContext, kind: str, value: str, legal_entity_id: UUID | None
) -> UUID:
    new_id = uuid4()
    if kind == "DEPARTMENT":
        await ctx.session.execute(
            text("""INSERT INTO org_units (tenant_id, id, name, type, legal_entity_id)
                    VALUES (:tid, :id, :name, 'DEPARTMENT', :le)"""),
            {"tid": ctx.tenant_id, "id": new_id, "name": value, "le": legal_entity_id},
        )
    elif kind == "LOCATION":
        await ctx.session.execute(
            text("""INSERT INTO locations (tenant_id, id, name, type, legal_entity_id)
                    VALUES (:tid, :id, :name, 'OFFICE', :le)"""),
            {"tid": ctx.tenant_id, "id": new_id, "name": value, "le": legal_entity_id},
        )
    else:
        await ctx.session.execute(
            text("INSERT INTO jobs (tenant_id, id, title) VALUES (:tid, :id, :name)"),
            {"tid": ctx.tenant_id, "id": new_id, "name": value},
        )
    return new_id


async def resolve_role(ctx: IntegrationContext, value: str | None) -> str:
    if value is None:
        return "EMPLOYEE"
    mapped = (
        await ctx.session.execute(
            text("""
            SELECT target_value FROM integration_mappings
            WHERE tenant_id = :tid AND app_id = :app AND kind = 'ROLE'
              AND lower(external_value) = lower(:v)
        """),
            {"tid": ctx.tenant_id, "app": ctx.app_id, "v": value.strip()},
        )
    ).scalar()
    role = (mapped or value).strip().upper()
    if role not in ("EMPLOYEE", "MANAGER"):
        # A fixed rule (plan §6.4): sync never grants HR, Accounts or Admin rights.
        raise SyncError(
            422,
            f"Role '{value}' can't be granted through sync. Map it to EMPLOYEE or MANAGER, or "
            "grant HR and admin roles in HRMS.",
            "ROLE_NOT_ALLOWED",
            {"kind": "ROLE", "value": value},
        )
    return role


async def _manager_employment(
    ctx: IntegrationContext, manager_external_id: str | None
) -> UUID | None:
    if not manager_external_id:
        return None
    return (
        await ctx.session.execute(
            text("""
            SELECT employment_id FROM external_identities
            WHERE tenant_id = :tid AND app_id = :app AND external_id = :ext
        """),
            {"tid": ctx.tenant_id, "app": ctx.app_id, "ext": manager_external_id},
        )
    ).scalar()


# ─── Ownership and ordering ──────────────────────────────────────────────────


def apply_ownership(
    body: EmployeeUpsert, settings: IntegrationSettings, *, creating: bool
) -> tuple[dict[str, Any], list[str]]:
    """The fields of this request the app may set. Creating a record sets everything it sends."""
    sent = body.model_dump(exclude_unset=True)
    kept: dict[str, Any] = {}
    warnings: list[str] = []
    dropped: list[str] = []
    for key, value in sent.items():
        field = PAYLOAD_FIELDS.get(key)
        if field is None or creating:
            kept[key] = value
            continue
        if settings.owner(field) in ("APP", "SHARED"):
            kept[key] = value
        else:
            dropped.append(key)
    if dropped:
        if settings.inbound_unowned == "REJECT":
            raise SyncError(
                422,
                f"These fields are owned by HRMS and can't be changed from this app: "
                f"{', '.join(sorted(dropped))}",
                "FIELD_OWNED_BY_HRMS",
                {"fields": sorted(dropped)},
            )
        warnings.append(f"FIELD_OWNED_BY_HRMS: ignored {', '.join(sorted(dropped))}")
    return kept, warnings


def _is_stale(identity: dict[str, Any], source_updated_at: datetime | None) -> bool:
    last = identity.get("last_source_updated_at")
    if source_updated_at is None or last is None:
        return False
    if source_updated_at.tzinfo is None:
        source_updated_at = source_updated_at.replace(tzinfo=UTC)
    return source_updated_at < last


# ─── Passwords and logins ────────────────────────────────────────────────────


async def _password_for_new_login(
    ctx: IntegrationContext, body: EmployeeUpsert, settings: IntegrationSettings, code: str
) -> tuple[str | None, bool]:
    """(bcrypt hash or None, must_change_password)."""
    logins = settings.logins
    if logins.password_source == "NONE":
        return None, False
    if logins.password_source == "APP_THEN_DEFAULT" and (body.password or body.password_hash):
        ctx.require("passwords.sync")
        return await _hash_from_body(ctx, body), False
    plain = password_from_pattern(
        logins.default_pattern, body.first_name or "", body.last_name or "", code
    )
    return await hash_plain(ctx, plain), logins.force_change


async def hash_plain(ctx: IntegrationContext, plain: str) -> str:
    """bcrypt is slow on purpose; a bulk call hashes its passwords in parallel up front."""
    cached = ctx.info.get("prehashed", {}).get(plain)
    return cached if cached is not None else await ahash_password(plain)


async def prehash_passwords(ctx: IntegrationContext, records: list[EmployeeUpsert]) -> None:
    """Hash every password a bulk call will need at once, across the bcrypt thread pool."""
    import asyncio

    from hrms.modules.integrations.profiles import tenant_settings

    pattern = (await tenant_settings(ctx.session, ctx.tenant_id, ctx.app_id))["logins"][
        "default_pattern"
    ]
    plains: set[str] = set()
    for r in records:
        if r.password:
            plains.add(r.password)
        elif not r.password_hash and r.first_name:
            plains.add(
                password_from_pattern(
                    pattern, r.first_name, r.last_name or "", r.employee_code or ""
                )
            )
    ordered = sorted(plains)
    hashes = await asyncio.gather(*(ahash_password(p) for p in ordered))
    ctx.info["prehashed"] = dict(zip(ordered, hashes, strict=True))


async def _hash_from_body(ctx: IntegrationContext, body: EmployeeUpsert) -> str:
    if body.password_hash is not None:
        if not BCRYPT_HASH.match(body.password_hash):
            raise SyncError(
                422,
                "password_hash must be a bcrypt hash ($2a$, $2b$ or $2y$, cost 10-14). Other "
                "formats are not accepted.",
                "UNSUPPORTED_PASSWORD_HASH",
            )
        return body.password_hash
    assert body.password is not None
    return await hash_plain(ctx, body.password)


async def _is_privileged(ctx: IntegrationContext, account_id: UUID) -> bool:
    """Whether a login holds any role beyond the EMPLOYEE/MANAGER that sync manages."""
    return bool(
        (
            await ctx.session.execute(
                text("""
                SELECT 1 FROM role_assignments ra
                JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                WHERE ra.tenant_id = :tid AND ra.user_account_id = :uid
                  AND r.name NOT IN ('EMPLOYEE', 'MANAGER')
                LIMIT 1
            """),
                {"tid": ctx.tenant_id, "uid": account_id},
            )
        ).first()
    )


async def _role_id(ctx: IntegrationContext, name: str) -> UUID:
    role_id = (
        await ctx.session.execute(
            text("SELECT id FROM roles WHERE tenant_id = :tid AND name = :name"),
            {"tid": ctx.tenant_id, "name": name},
        )
    ).scalar()
    if role_id is None:
        raise HTTPException(500, f"The {name} role is missing for this company")
    return role_id


async def _set_role(ctx: IntegrationContext, account_id: UUID, role: str) -> bool:
    """Make the login's sync-managed role EMPLOYEE or MANAGER. Other roles are left alone."""
    # Serialise role changes for this login: two syncs at once would each see "no current
    # role" and both insert (uq_role_assignments_grant would then refuse the second).
    await ctx.session.execute(
        text("SELECT 1 FROM user_accounts WHERE tenant_id = :tid AND id = :uid FOR UPDATE"),
        {"tid": ctx.tenant_id, "uid": account_id},
    )
    current = (
        (
            await ctx.session.execute(
                text("""
                SELECT ra.id, r.name FROM role_assignments ra
                JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                WHERE ra.tenant_id = :tid AND ra.user_account_id = :uid
                  AND r.name IN ('EMPLOYEE', 'MANAGER')
            """),
                {"tid": ctx.tenant_id, "uid": account_id},
            )
        )
        .mappings()
        .all()
    )
    if [r["name"] for r in current] == [role]:
        return False
    for r in current:
        await ctx.session.execute(
            text("DELETE FROM role_assignments WHERE tenant_id = :tid AND id = :id"),
            {"tid": ctx.tenant_id, "id": r["id"]},
        )
    ctx.session.add(
        RoleAssignment(
            tenant_id=ctx.tenant_id,
            id=uuid4(),
            user_account_id=account_id,
            role_id=await _role_id(ctx, role),
            scope_type="SELF" if role == "EMPLOYEE" else "DIRECT_REPORTS",
            scope_value=None,
        )
    )
    await ctx.session.flush()
    return True


async def _check_contact_unique(
    ctx: IntegrationContext, *, email: str | None, mobile: str | None, account_id: UUID | None
) -> None:
    if email:
        # Sign-in emails are unique across every company, so look beyond this tenant, through
        # the same SECURITY DEFINER lookup sign-in uses (it reveals only that the email is used).
        taken = (
            await ctx.session.execute(
                text("""
                SELECT 1 FROM login_lookup(:v) l
                WHERE CAST(:uid AS uuid) IS NULL OR l.id <> :uid
                LIMIT 1
            """),
                {"v": email, "uid": account_id},
            )
        ).first()
        if taken:
            raise SyncError(409, "Another login already uses this email", "EMAIL_IN_USE")
    if mobile:
        taken = (
            await ctx.session.execute(
                text("""
                SELECT 1 FROM user_accounts WHERE tenant_id = :tid AND mobile = :v
                  AND status = 'ACTIVE' AND (CAST(:uid AS uuid) IS NULL OR id <> :uid)
            """),
                {"tid": ctx.tenant_id, "v": mobile, "uid": account_id},
            )
        ).first()
        if taken:
            raise SyncError(409, "Another active login already uses this mobile", "MOBILE_IN_USE")


# ─── Employee codes (D-8) ────────────────────────────────────────────────────


async def _scheme(ctx: IntegrationContext, legal_entity_id: UUID) -> dict[str, Any] | None:
    for clause in ("legal_entity_id = :le", "legal_entity_id IS NULL"):
        row = (
            (
                await ctx.session.execute(
                    text(f"""
                    SELECT id, prefix, separator, number_digits FROM employee_id_schemes
                    WHERE tenant_id = :tid AND archived_at IS NULL AND {clause} LIMIT 1
                """),
                    {"tid": ctx.tenant_id, "le": legal_entity_id},
                )
            )
            .mappings()
            .first()
        )
        if row:
            return dict(row)
    return None


async def _code_in_use(ctx: IntegrationContext, legal_entity_id: UUID, code: str) -> bool:
    return bool(
        (
            await ctx.session.execute(
                text("""
                SELECT 1 FROM employments WHERE tenant_id = :tid AND legal_entity_id = :le
                  AND lower(employee_number) = lower(:code)
            """),
                {"tid": ctx.tenant_id, "le": legal_entity_id, "code": code},
            )
        ).first()
    )


async def employee_code_for_new_hire(
    ctx: IntegrationContext, legal_entity_id: UUID, sent: str | None
) -> str:
    from hrms.modules.people.router import _generate_employee_number

    scheme = await _scheme(ctx, legal_entity_id)
    if sent:
        if await _code_in_use(ctx, legal_entity_id, sent):
            raise SyncError(409, f"Employee code {sent} is already used", "EMPLOYEE_CODE_IN_USE")
        if scheme:
            # A code in the scheme's own pattern moves the counter past it, so HRMS never
            # issues the same number later.
            pattern = re.escape(scheme["prefix"] + scheme["separator"]) + r"(\d+)$"
            match = re.match(pattern, sent, re.IGNORECASE)
            if match:
                await ctx.session.execute(
                    text("""
                    UPDATE employee_id_schemes SET next_number = GREATEST(next_number, :n)
                    WHERE tenant_id = :tid AND id = :sid
                """),
                    {"tid": ctx.tenant_id, "sid": scheme["id"], "n": int(match.group(1)) + 1},
                )
        return sent
    if scheme is None:
        raise SyncError(
            422,
            "employee_code is required: this company has no employee ID scheme in HRMS",
            "EMPLOYEE_CODE_REQUIRED",
        )
    code = await _generate_employee_number(ctx.session, ctx.tenant_id, legal_entity_id)
    assert code is not None
    return code


# ─── Personnel actions ───────────────────────────────────────────────────────


def _action_key(ctx: IntegrationContext, suffix: str) -> str:
    # The prefix lets the events hook tell which app made the change (so it isn't sent back).
    return f"int:{ctx.app_id}:{suffix}"[:100]


async def _personnel_action(
    ctx: IntegrationContext,
    emp: Employment,
    action_type: PersonnelActionType,
    effective: date,
    changes: dict[str, Any] | None,
    *,
    reason_code: str | None = None,
) -> PersonnelAction:
    from hrms.modules.people.router import _apply_personnel_action, _reject_conflicting_schedule

    await lock_resource(ctx.session, ctx.tenant_id, f"personnel:{emp.id}")
    await _reject_conflicting_schedule(ctx.session, ctx.tenant_id, emp.id, action_type, effective)
    pa = PersonnelAction(
        tenant_id=ctx.tenant_id,
        id=uuid4(),
        employment_id=emp.id,
        type=action_type,
        reason_code=reason_code,
        effective_date=effective,
        changes=changes,
        status=PersonnelActionStatus.PENDING_APPROVAL,
        idempotency_key=_action_key(ctx, uuid4().hex),
        submitted_at=datetime.now(UTC),
    )
    ctx.session.add(pa)
    await ctx.session.flush()
    if effective > business_today():
        pa.status = PersonnelActionStatus.SCHEDULED
    else:
        await _apply_personnel_action(ctx.session, ctx.tenant_id, pa, emp)
        pa.status = PersonnelActionStatus.APPLIED
        pa.applied_at = datetime.now(UTC)
    ctx.session.add(pa)
    await ctx.session.flush()
    if pa.status == PersonnelActionStatus.SCHEDULED:
        from hrms.modules.integrations.hooks import personnel_action_scheduled

        await personnel_action_scheduled(ctx.session, ctx.tenant_id, pa, emp)
    return pa


async def _load_employment(ctx: IntegrationContext, employment_id: UUID) -> Employment:
    emp = (
        (
            await ctx.session.execute(
                select(Employment)
                .where(Employment.tenant_id == ctx.tenant_id)
                .where(Employment.id == employment_id)
            )
        )
        .scalars()
        .first()
    )
    if emp is None:
        raise HTTPException(404, "Employee not found")
    return emp


async def _load_person(ctx: IntegrationContext, person_id: UUID) -> Person:
    person = (
        (
            await ctx.session.execute(
                select(Person)
                .where(Person.tenant_id == ctx.tenant_id)
                .where(Person.id == person_id)
            )
        )
        .scalars()
        .one()
    )
    return person


async def _load_account(ctx: IntegrationContext, employment_id: UUID) -> UserAccount | None:
    return (
        (
            await ctx.session.execute(
                select(UserAccount)
                .where(UserAccount.tenant_id == ctx.tenant_id)
                .where(UserAccount.employment_id == employment_id)
            )
        )
        .scalars()
        .first()
    )


async def _resolve_pending_managers(
    ctx: IntegrationContext, external_id: str, employment_id: UUID
) -> int:
    """People whose manager this new employee is, now that the manager exists."""
    from hrms.modules.people.router import _current_assignment

    waiting = (
        (
            await ctx.session.execute(
                text("""
                SELECT id, employment_id FROM external_identities
                WHERE tenant_id = :tid AND app_id = :app AND pending_manager_external_id = :ext
            """),
                {"tid": ctx.tenant_id, "app": ctx.app_id, "ext": external_id},
            )
        )
        .mappings()
        .all()
    )
    linked = 0
    for row in waiting:
        report = await _load_employment(ctx, row["employment_id"])
        if await _current_assignment(ctx.session, ctx.tenant_id, report.id) is not None:
            await _personnel_action(
                ctx,
                report,
                PersonnelActionType.CHANGE_MANAGER,
                business_today(),
                {"manager_employment_id": str(employment_id)},
            )
            linked += 1
        await ctx.session.execute(
            text("""
            UPDATE external_identities SET pending_manager_external_id = NULL, updated_at = now()
            WHERE tenant_id = :tid AND id = :id
        """),
            {"tid": ctx.tenant_id, "id": row["id"]},
        )
    return linked


# ─── Matching an unlinked HRMS employee ──────────────────────────────────────


async def _match(
    ctx: IntegrationContext, external_id: str, body: EmployeeUpsert, settings: IntegrationSettings
) -> UUID | None:
    """
    The unlinked HRMS employee this record is, if the matching rule says so. A partial match
    is queued for HR as a possible duplicate and refused (409), so nobody is created twice.
    """
    session = ctx.session
    if body.employment_id:
        emp_id = to_uuid(body.employment_id)
        linked = (
            await session.execute(
                text("""
                SELECT external_id FROM external_identities
                WHERE tenant_id = :tid AND app_id = :app AND employment_id = :eid
            """),
                {"tid": ctx.tenant_id, "app": ctx.app_id, "eid": emp_id},
            )
        ).scalar()
        if linked:
            raise SyncError(
                409,
                f"This employee is already linked to {linked} in this app",
                "ALREADY_LINKED",
                {"external_id": linked},
            )
        await _load_employment(ctx, emp_id)
        return emp_id

    unlinked = """
        FROM employments e
        JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
        LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
        WHERE e.tenant_id = :tid AND e.archived_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM external_identities x
                          WHERE x.tenant_id = e.tenant_id AND x.app_id = :app
                            AND x.employment_id = e.id)
    """
    params = {"tid": ctx.tenant_id, "app": ctx.app_id}
    candidates: dict[UUID, dict[str, Any]] = {}
    if body.employee_code:
        for r in (
            await session.execute(
                text(f"""SELECT e.id, p.legal_first_name, p.legal_last_name, p.date_of_birth,
                                ua.email {unlinked} AND lower(e.employee_number) = lower(:code)"""),
                {**params, "code": body.employee_code},
            )
        ).mappings():
            candidates[r["id"]] = dict(r)
    if not candidates:
        for column, value in (("ua.email", body.email), ("ua.mobile", body.mobile)):
            if value:
                for r in (
                    await session.execute(
                        text(f"""SELECT e.id {unlinked} AND lower({column}) = lower(:v)"""),
                        {**params, "v": str(value)},
                    )
                ).mappings():
                    candidates.setdefault(r["id"], {"id": r["id"], "contact_only": True})
    if not candidates:
        return None

    def full_match(c: dict[str, Any]) -> bool:
        if c.get("contact_only") or settings.matching == "NEVER":
            return False
        if settings.matching == "CODE_EMAIL":
            return bool(body.email and c.get("email") and c["email"].lower() == body.email.lower())
        names = (
            body.first_name
            and body.last_name
            and c["legal_first_name"].lower() == body.first_name.strip().lower()
            and c["legal_last_name"].lower() == body.last_name.strip().lower()
        )
        dob_or_email = (body.date_of_birth and c.get("date_of_birth") == body.date_of_birth) or (
            body.email and c.get("email") and c["email"].lower() == body.email.lower()
        )
        return bool(names and dob_or_email)

    full = [c for c in candidates.values() if full_match(c)]
    if len(full) == 1 and len(candidates) == 1:
        return full[0]["id"]
    duplicates = [
        {
            "employment_id": str(c["id"]),
            "reason": "Same employee code, other details differ"
            if not c.get("contact_only")
            else "Same email or mobile, other details differ",
        }
        for c in candidates.values()
    ]
    first = next(iter(candidates))
    raise SyncError(
        409,
        "An unlinked HRMS employee looks like this person. HR must confirm or reject the match "
        "on the Possible duplicates tab; then retry.",
        "POSSIBLE_DUPLICATE",
        {
            "employment_id": to_typed_id("employment", first),
            "duplicates": duplicates,
            "payload": json.loads(body.model_dump_json(exclude={"password", "password_hash"})),
        },
    )


# ─── Create ──────────────────────────────────────────────────────────────────


async def link_identity(
    ctx: IntegrationContext,
    external_id: str,
    employment_id: UUID,
    source_updated_at: datetime | None,
) -> None:
    account = await _load_account(ctx, employment_id)
    await ctx.session.execute(
        text("""
        INSERT INTO external_identities
            (tenant_id, id, app_id, external_id, employment_id, user_account_id,
             last_source_updated_at)
        VALUES (:tid, :id, :app, :ext, :eid, :uid, :src)
    """),
        {
            "tid": ctx.tenant_id,
            "id": uuid4(),
            "app": ctx.app_id,
            "ext": external_id,
            "eid": employment_id,
            "uid": account.id if account else None,
            "src": source_updated_at,
        },
    )
    from hrms.modules.integrations.hooks import complete_onboarding_tasks

    await complete_onboarding_tasks(ctx.session, ctx.tenant_id, ctx.app_id, [employment_id])


async def create_employee(
    ctx: IntegrationContext, external_id: str, body: EmployeeUpsert
) -> SyncResult:
    session = ctx.session
    sent = body.model_dump(exclude_unset=True)
    if body.employment_id:
        # Linking an employee hired in HRMS: their company is already known.
        emp = await _load_employment(ctx, to_uuid(body.employment_id))
        if not ctx.covers_entity(emp.legal_entity_id):
            raise SyncError(403, "This key can't write to this company", "ENTITY_NOT_ALLOWED")
        settings = await settings_for(ctx, emp.legal_entity_id)
        matched = await _match(ctx, external_id, body, settings)
    else:
        if not body.company:
            raise SyncError(
                422,
                "company is required to create an employee",
                "FIELD_REQUIRED",
                {"field": "company"},
            )
        legal_entity_id = await resolve(
            ctx, "LEGAL_ENTITY", body.company, legal_entity_id=None, settings=None
        )
        if not ctx.covers_entity(legal_entity_id):
            raise SyncError(403, "This key can't write to this company", "ENTITY_NOT_ALLOWED")
        settings = await settings_for(ctx, legal_entity_id)
        matched = await _match(ctx, external_id, body, settings)
    if matched is not None:
        await link_identity(ctx, external_id, matched, None)
        session.info["integration_linked"] = True
        result = await update_employee(ctx, external_id, body, linked_just_now=True)
        result.outcome = "LINKED"
        return result

    if settings.lifecycle.hire == "HRMS":
        raise SyncError(
            403,
            "New employees for this company are hired in HRMS, not through this app",
            "OPERATION_NOT_ALLOWED",
        )
    missing = [
        f
        for f in ("first_name", "last_name", "department", "designation", "hire_date")
        if not sent.get(f)
    ]
    if missing:
        raise SyncError(
            422,
            f"Required to create an employee: {', '.join(missing)}",
            "FIELD_REQUIRED",
            {"fields": missing},
        )
    # Checked present above; narrowed here for the type checker.
    assert body.department and body.designation and body.hire_date
    assert body.first_name and body.last_name
    role = await resolve_role(ctx, body.role)
    org_unit_id = await resolve(
        ctx, "DEPARTMENT", body.department, legal_entity_id=legal_entity_id, settings=settings
    )
    job_id = await resolve(
        ctx, "DESIGNATION", body.designation, legal_entity_id=legal_entity_id, settings=settings
    )
    if body.location:
        location_id = await resolve(
            ctx, "LOCATION", body.location, legal_entity_id=legal_entity_id, settings=settings
        )
    elif settings.default_location_id:
        location_id = to_uuid(settings.default_location_id)
    else:
        raise SyncError(
            422,
            "location is required (or set a default location for this company)",
            "FIELD_REQUIRED",
            {"fields": ["location"]},
        )
    await _check_contact_unique(ctx, email=body.email, mobile=body.mobile, account_id=None)
    code = await employee_code_for_new_hire(ctx, legal_entity_id, body.employee_code)

    warnings: list[str] = []
    manager_id = await _manager_employment(ctx, body.manager_external_id)
    pending_manager = None
    if body.manager_external_id and manager_id is None:
        pending_manager = body.manager_external_id
        warnings.append("MANAGER_PENDING: the manager is not synced yet; linked when they are")

    person = Person(
        tenant_id=ctx.tenant_id,
        id=uuid4(),
        legal_first_name=body.first_name.strip(),
        legal_last_name=body.last_name.strip(),
        preferred_name=body.preferred_name,
        date_of_birth=body.date_of_birth,
        gender=body.gender,
    )
    session.add(person)
    emp = Employment(
        tenant_id=ctx.tenant_id,
        id=uuid4(),
        person_id=person.id,
        legal_entity_id=legal_entity_id,
        employee_number=code,
        hire_date=body.hire_date,
    )
    session.add(emp)
    await session.flush()

    password_hash, must_change = await _password_for_new_login(ctx, body, settings, code)
    account = UserAccount(
        tenant_id=ctx.tenant_id,
        id=uuid4(),
        email=str(body.email) if body.email else None,
        mobile=body.mobile,
        employee_code=code,
        password_hash=password_hash,
        must_change_password=must_change,
        employment_id=emp.id,
        status="ACTIVE",
    )
    session.add(account)
    await session.flush()
    await _set_role(ctx, account.id, role)

    await session.execute(
        text("""
        INSERT INTO external_identities
            (tenant_id, id, app_id, external_id, employment_id, user_account_id,
             pending_manager_external_id, last_source_updated_at)
        VALUES (:tid, :id, :app, :ext, :eid, :uid, :pending, :src)
    """),
        {
            "tid": ctx.tenant_id,
            "id": uuid4(),
            "app": ctx.app_id,
            "ext": external_id,
            "eid": emp.id,
            "uid": account.id,
            "pending": pending_manager,
            "src": body.source_updated_at,
        },
    )
    changes = {
        "org_unit_id": str(org_unit_id),
        "location_id": str(location_id),
        "job_id": str(job_id),
    }
    if manager_id:
        changes["manager_employment_id"] = str(manager_id)
    await _personnel_action(ctx, emp, PersonnelActionType.HIRE, body.hire_date, changes)
    linked = await _resolve_pending_managers(ctx, external_id, emp.id)
    if linked:
        warnings.append(f"Linked as manager of {linked} employee(s) who were waiting")
    return SyncResult(
        outcome="CREATED",
        external_id=external_id,
        employment_id=to_typed_id("employment", emp.id),
        user_id=to_typed_id("user", account.id),
        employee_code=code,
        warnings=warnings,
    )


# ─── Update ──────────────────────────────────────────────────────────────────


async def update_employee(
    ctx: IntegrationContext,
    external_id: str,
    body: EmployeeUpsert,
    *,
    linked_just_now: bool = False,
) -> SyncResult:
    from hrms.modules.people.router import _current_assignment, _current_line_manager

    session = ctx.session
    identity = await find_identity(ctx, external_id)
    assert identity is not None
    emp = await _load_employment(ctx, identity["employment_id"])
    result = SyncResult(
        outcome="UPDATED",
        external_id=external_id,
        employment_id=to_typed_id("employment", emp.id),
        employee_code=emp.employee_number,
    )
    if not linked_just_now and _is_stale(identity, body.source_updated_at):
        result.outcome = "STALE_IGNORED"
        result.warnings.append(
            "STALE_IGNORED: a newer update for this employee was already applied"
        )
        return result
    if not ctx.covers_entity(emp.legal_entity_id):
        raise SyncError(403, "This key can't write to this company", "ENTITY_NOT_ALLOWED")
    settings = await settings_for(ctx, emp.legal_entity_id)
    fields, warnings = apply_ownership(body, settings, creating=False)
    result.warnings.extend(warnings)
    changes: dict[str, dict[str, Any]] = {}

    if "company" in fields:
        target = await resolve(
            ctx, "LEGAL_ENTITY", fields["company"], legal_entity_id=None, settings=None
        )
        if target != emp.legal_entity_id:
            raise SyncError(
                422,
                "Moving an employee to another company is an exit and a new hire in HRMS, not an "
                "update. Exit them, then send the new employment with a new external ID.",
                "COMPANY_CHANGE_NOT_SUPPORTED",
            )

    person = await _load_person(ctx, emp.person_id)
    for key, attr in (
        ("first_name", "legal_first_name"),
        ("last_name", "legal_last_name"),
        ("preferred_name", "preferred_name"),
        ("date_of_birth", "date_of_birth"),
        ("gender", "gender"),
    ):
        if key in fields:
            new = fields[key].strip() if isinstance(fields[key], str) else fields[key]
            if key in ("first_name", "last_name") and not new:
                raise SyncError(422, f"{key} can't be empty", "FIELD_REQUIRED", {"field": key})
            old = getattr(person, attr)
            if old != new:
                changes[key] = {"old": _plain(old), "new": _plain(new)}
                setattr(person, attr, new)
    if any(
        k in changes
        for k in ("first_name", "last_name", "preferred_name", "date_of_birth", "gender")
    ):
        person.version += 1
        session.add(person)

    account = await _load_account(ctx, emp.id)
    if account is not None and await _is_privileged(ctx, account.id):
        # A login with HR, Accounts or Admin rights is managed only in HRMS: an app must not be
        # able to set its password or change how it signs in, or a key could take it over.
        touched = sorted(
            k
            for k in ("email", "mobile", "employee_code", "password", "password_hash")
            if k in fields
            and not (
                k == "email" and (account.email or None) == (str(fields[k]) if fields[k] else None)
            )
            and not (k == "mobile" and account.mobile == fields[k])
            and not (k == "employee_code" and emp.employee_number == fields[k])
        )
        if touched:
            raise SyncError(
                403,
                "This employee's login has HR or admin rights, so its sign-in details and "
                f"password are managed only in HRMS ({', '.join(touched)}).",
                "PRIVILEGED_ACCOUNT_PROTECTED",
                {"fields": touched},
            )
    if account is not None:
        new_email = str(fields["email"]) if fields.get("email") else fields.get("email")
        if "email" in fields and (account.email or None) != (new_email or None):
            await _check_contact_unique(ctx, email=new_email, mobile=None, account_id=account.id)
            changes["email"] = {"old": account.email, "new": new_email}
            account.email = new_email
        if "mobile" in fields and account.mobile != fields["mobile"]:
            await _check_contact_unique(
                ctx, email=None, mobile=fields["mobile"], account_id=account.id
            )
            changes["mobile"] = {"old": account.mobile, "new": fields["mobile"]}
            account.mobile = fields["mobile"]
        if "role" in fields:
            role = await resolve_role(ctx, fields["role"])
            if await _set_role(ctx, account.id, role):
                changes["role"] = {"old": None, "new": role}
        if fields.get("password") or fields.get("password_hash"):
            ctx.require("passwords.sync")
            account.password_hash = await _hash_from_body(ctx, body)
            account.must_change_password = False
            account.password_changed_at = datetime.now(UTC)
            account.token_epoch += 1
            changes["password"] = {"old": "…", "new": "changed"}
        session.add(account)

    if (
        "employee_code" in fields
        and fields["employee_code"]
        and (fields["employee_code"] != emp.employee_number)
    ):
        if await _code_in_use(ctx, emp.legal_entity_id, fields["employee_code"]):
            raise SyncError(
                409,
                f"Employee code {fields['employee_code']} is already used",
                "EMPLOYEE_CODE_IN_USE",
            )
        changes["employee_code"] = {"old": emp.employee_number, "new": fields["employee_code"]}
        emp.employee_number = fields["employee_code"]
        if account is not None:
            account.employee_code = fields["employee_code"]
            session.add(account)
    if "hire_date" in fields and fields["hire_date"] and fields["hire_date"] != emp.hire_date:
        changes["hire_date"] = {
            "old": emp.hire_date.isoformat(),
            "new": fields["hire_date"].isoformat(),
        }
        emp.hire_date = fields["hire_date"]
        session.add(emp)
        await session.flush()
        await _move_scheduled_hire(ctx, emp)
        await reschedule_held_hire(session, ctx.tenant_id, emp.id)
    session.add(emp)
    await session.flush()

    # Job: department, location, designation, manager.
    job_sent = [k for k in JOB_FIELDS if k in fields]
    if job_sent:
        current = await _current_assignment(session, ctx.tenant_id, emp.id)
        action_changes: dict[str, Any] = {}
        if "department" in fields and fields["department"]:
            ou = await resolve(
                ctx,
                "DEPARTMENT",
                fields["department"],
                legal_entity_id=emp.legal_entity_id,
                settings=settings,
            )
            if current is None or ou != current.org_unit_id:
                action_changes["org_unit_id"] = str(ou)
        if "location" in fields and fields["location"]:
            loc = await resolve(
                ctx,
                "LOCATION",
                fields["location"],
                legal_entity_id=emp.legal_entity_id,
                settings=settings,
            )
            if current is None or loc != current.location_id:
                action_changes["location_id"] = str(loc)
        if "designation" in fields and fields["designation"]:
            job = await resolve(
                ctx,
                "DESIGNATION",
                fields["designation"],
                legal_entity_id=emp.legal_entity_id,
                settings=settings,
            )
            if current is None or job != current.job_id:
                action_changes["job_id"] = str(job)
        if "manager_external_id" in fields:
            manager_id = await _manager_employment(ctx, fields["manager_external_id"])
            current_manager = (
                await _current_line_manager(session, ctx.tenant_id, current.id) if current else None
            )
            if fields["manager_external_id"] and manager_id is None:
                await session.execute(
                    text("""
                    UPDATE external_identities SET pending_manager_external_id = :m
                    WHERE tenant_id = :tid AND app_id = :app AND external_id = :ext
                """),
                    {
                        "tid": ctx.tenant_id,
                        "app": ctx.app_id,
                        "ext": external_id,
                        "m": fields["manager_external_id"],
                    },
                )
                result.warnings.append(
                    "MANAGER_PENDING: the manager is not synced yet; linked when they are"
                )
            elif manager_id is not None and manager_id != current_manager:
                if manager_id == emp.id:
                    raise SyncError(422, "An employee can't manage themselves", "INVALID_MANAGER")
                action_changes["manager_employment_id"] = str(manager_id)
        if action_changes and current is None:
            # Linked to an HRMS employee who was never placed: this is their first placement.
            await _first_placement(ctx, emp, action_changes, settings)
            for key, label in (
                ("org_unit_id", "department"),
                ("location_id", "location"),
                ("job_id", "designation"),
                ("manager_employment_id", "manager"),
            ):
                if key in action_changes:
                    changes[label] = {"old": None, "new": action_changes[key]}
            action_changes = {}
        if action_changes:
            if settings.lifecycle.job_change == "HRMS":
                raise SyncError(
                    403, "Job changes for this company are made in HRMS", "OPERATION_NOT_ALLOWED"
                )
            for key, label in (
                ("org_unit_id", "department"),
                ("location_id", "location"),
                ("job_id", "designation"),
                ("manager_employment_id", "manager"),
            ):
                if key in action_changes:
                    changes[label] = {"old": None, "new": action_changes[key]}
            effective = body.effective_date or business_today()
            if body.change_reason == "CORRECTION":
                await _correct_assignment(ctx, emp, current, action_changes)
            else:
                if set(action_changes) == {"manager_employment_id"}:
                    kind = PersonnelActionType.CHANGE_MANAGER
                elif body.change_reason == "PROMOTION":
                    kind = PersonnelActionType.PROMOTION
                else:
                    kind = PersonnelActionType.TRANSFER
                assert current is not None
                if effective < current.effective_from:
                    raise SyncError(
                        422,
                        "effective_date is before the current placement started",
                        "INVALID_EFFECTIVE_DATE",
                    )
                if effective == current.effective_from:
                    await _correct_assignment(ctx, emp, current, action_changes)
                else:
                    await _personnel_action(ctx, emp, kind, effective, action_changes)

    await _touch_source(ctx, external_id, body.source_updated_at)
    non_job = {
        k: v
        for k, v in changes.items()
        if k not in ("department", "location", "designation", "manager")
    }
    if non_job:
        from hrms.modules.integrations.events import emit_employee_event

        await emit_employee_event(
            session,
            ctx.tenant_id,
            emp.id,
            "employee.updated",
            changes={k: v for k, v in non_job.items() if k != "password"} or None,
        )
    result.changes = changes or None
    if not changes and result.outcome == "UPDATED":
        result.outcome = "NO_CHANGE"
    if account is not None:
        result.user_id = to_typed_id("user", account.id)
    result.employee_code = emp.employee_number
    return result


async def _move_scheduled_hire(ctx: IntegrationContext, emp: Employment) -> None:
    """A joining date that moves takes the still-scheduled hire with it (applied now if due)."""
    from hrms.modules.people.router import _apply_personnel_action

    pa = (
        (
            await ctx.session.execute(
                select(PersonnelAction)
                .where(PersonnelAction.tenant_id == ctx.tenant_id)
                .where(PersonnelAction.employment_id == emp.id)
                .where(PersonnelAction.type == PersonnelActionType.HIRE)
                .where(PersonnelAction.status == PersonnelActionStatus.SCHEDULED)
            )
        )
        .scalars()
        .first()
    )
    if pa is None:
        return
    pa.effective_date = emp.hire_date
    if emp.hire_date <= business_today():
        await _apply_personnel_action(ctx.session, ctx.tenant_id, pa, emp)
        pa.status = PersonnelActionStatus.APPLIED
        pa.applied_at = datetime.now(UTC)
    ctx.session.add(pa)
    await ctx.session.flush()


async def _first_placement(
    ctx: IntegrationContext,
    emp: Employment,
    placement: dict[str, Any],
    settings: IntegrationSettings,
) -> None:
    if emp.employment_state == EmploymentState.SEPARATED:
        raise SyncError(409, "This employee has left. Rehire them first.", "NOT_ACTIVE")
    scheduled = (
        await ctx.session.execute(
            text("""
            SELECT effective_date FROM personnel_actions
            WHERE tenant_id = :tid AND employment_id = :eid AND type = 'HIRE'
              AND status = 'SCHEDULED'
        """),
            {"tid": ctx.tenant_id, "eid": emp.id},
        )
    ).scalar()
    if scheduled is not None:
        raise SyncError(
            409,
            f"This employee's hire is scheduled for {scheduled}. Change the placement after it "
            "starts.",
            "HIRE_SCHEDULED",
        )
    if "location_id" not in placement and settings.default_location_id:
        placement["location_id"] = str(to_uuid(settings.default_location_id))
    missing = [
        label
        for key, label in (
            ("org_unit_id", "department"),
            ("location_id", "location"),
            ("job_id", "designation"),
        )
        if key not in placement
    ]
    if missing:
        raise SyncError(
            422,
            f"This employee has no placement yet. Send {', '.join(missing)} to place them.",
            "FIELD_REQUIRED",
            {"fields": missing},
        )
    await _personnel_action(ctx, emp, PersonnelActionType.HIRE, emp.hire_date, placement)


async def _correct_assignment(ctx: IntegrationContext, emp: Employment, current, action_changes):
    """A correction fixes the current placement in place, without a new history slice."""
    from hrms.modules.integrations.hooks import employee_changed
    from hrms.modules.people.models import AssignmentManager

    before = await employee_changed.before(ctx.session, ctx.tenant_id, emp.id)
    for key, attr in (
        ("org_unit_id", "org_unit_id"),
        ("location_id", "location_id"),
        ("job_id", "job_id"),
    ):
        if key in action_changes:
            setattr(current, attr, UUID(action_changes[key]))
    ctx.session.add(current)
    if "manager_employment_id" in action_changes:
        await ctx.session.execute(
            text("""
            UPDATE assignment_managers SET manager_employment_id = :m
            WHERE tenant_id = :tid AND assignment_id = :a AND manager_type = 'LINE'
              AND effective_to IS NULL
        """),
            {
                "tid": ctx.tenant_id,
                "a": current.id,
                "m": UUID(action_changes["manager_employment_id"]),
            },
        )
        exists = (
            await ctx.session.execute(
                text("""SELECT 1 FROM assignment_managers WHERE tenant_id = :tid
                        AND assignment_id = :a AND manager_type = 'LINE'
                        AND effective_to IS NULL"""),
                {"tid": ctx.tenant_id, "a": current.id},
            )
        ).first()
        if not exists:
            ctx.session.add(
                AssignmentManager(
                    tenant_id=ctx.tenant_id,
                    id=uuid4(),
                    assignment_id=current.id,
                    manager_employment_id=UUID(action_changes["manager_employment_id"]),
                    manager_type="LINE",
                    effective_from=current.effective_from,
                )
            )
    await ctx.session.flush()
    await employee_changed.after(ctx.session, ctx.tenant_id, emp.id, before)


def _plain(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


# ─── Exit and rehire ─────────────────────────────────────────────────────────


async def exits_today(ctx: IntegrationContext) -> int:
    return (
        await ctx.session.execute(
            text("""
            SELECT count(*) FROM integration_requests
            WHERE tenant_id = :tid AND app_id = :app AND operation = 'EXIT'
              AND outcome IN ('APPLIED', 'SCHEDULED', 'HELD_FOR_REVIEW')
              AND created_at > now() - interval '24 hours'
        """),
            {"tid": ctx.tenant_id, "app": ctx.app_id},
        )
    ).scalar_one()


async def exit_limit(ctx: IntegrationContext, settings: IntegrationSettings) -> int:
    headcount = (
        await ctx.session.execute(
            text("""
            SELECT count(*) FROM employments
            WHERE tenant_id = :tid AND employment_state <> 'SEPARATED' AND archived_at IS NULL
        """),
            {"tid": ctx.tenant_id},
        )
    ).scalar_one()
    # The smaller of the count and the share, but never fewer than 3 a day, so a small company
    # can still process an ordinary day's leavers without HR releasing each one.
    by_share = max(3, math.floor(headcount * settings.safety.max_exit_percent / 100))
    return min(settings.safety.max_exits_per_day, by_share)


async def exit_employee(
    ctx: IntegrationContext, external_id: str, body: ExitRequest, *, released: bool = False
) -> SyncResult:
    identity = await find_identity(ctx, external_id)
    if identity is None:
        raise SyncError(404, "No employee is linked to this external ID", "NOT_LINKED")
    emp = await _load_employment(ctx, identity["employment_id"])
    result = SyncResult(
        outcome="SCHEDULED",
        external_id=external_id,
        employment_id=to_typed_id("employment", emp.id),
        employee_code=emp.employee_number,
    )
    if _is_stale(identity, body.source_updated_at):
        result.outcome = "STALE_IGNORED"
        return result
    if not ctx.covers_entity(emp.legal_entity_id):
        raise SyncError(403, "This key can't write to this company", "ENTITY_NOT_ALLOWED")
    settings = await settings_for(ctx, emp.legal_entity_id)
    if settings.lifecycle.exit == "HRMS":
        raise SyncError(403, "Exits for this company are made in HRMS", "OPERATION_NOT_ALLOWED")
    if emp.employment_state == EmploymentState.SEPARATED:
        result.outcome = "NO_CHANGE"
        result.warnings.append("Already separated")
        return result
    if not released and await exits_today(ctx) >= await exit_limit(ctx, settings):
        if settings.safety.over_limit == "REJECT":
            raise SyncError(
                429,
                "This app has reached its exit limit for the last 24 hours",
                "EXIT_LIMIT_REACHED",
            )
        result.outcome = "HELD_FOR_REVIEW"
        # Kept in the log, so HR can release exactly this exit later.
        result.changes = {
            "last_working_day": {"old": None, "new": body.last_working_day.isoformat()},
            "reason_code": {"old": None, "new": body.reason_code},
        }
        result.warnings.append(
            "HELD_FOR_REVIEW: more exits than the safety limit in 24 hours; HR must release it"
        )
        return result
    pa = await _personnel_action(
        ctx,
        emp,
        PersonnelActionType.SEPARATION,
        body.last_working_day,
        None,
        reason_code=body.reason_code,
    )
    result.outcome = "APPLIED" if pa.status == PersonnelActionStatus.APPLIED else "SCHEDULED"
    result.changes = {"last_working_day": {"old": None, "new": body.last_working_day.isoformat()}}
    await _touch_source(ctx, external_id, body.source_updated_at)
    return result


async def rehire_employee(
    ctx: IntegrationContext, external_id: str, body: RehireRequest
) -> SyncResult:
    from hrms.modules.people.models import Assignment

    identity = await find_identity(ctx, external_id)
    if identity is None:
        raise SyncError(404, "No employee is linked to this external ID", "NOT_LINKED")
    emp = await _load_employment(ctx, identity["employment_id"])
    if not ctx.covers_entity(emp.legal_entity_id):
        raise SyncError(403, "This key can't write to this company", "ENTITY_NOT_ALLOWED")
    settings = await settings_for(ctx, emp.legal_entity_id)
    if settings.lifecycle.rehire == "HRMS":
        raise SyncError(403, "Rehires for this company are made in HRMS", "OPERATION_NOT_ALLOWED")
    if emp.employment_state != EmploymentState.SEPARATED:
        raise SyncError(409, "Only a separated employee can be rehired", "NOT_SEPARATED")
    last = (
        (
            await ctx.session.execute(
                select(Assignment)
                .where(Assignment.tenant_id == ctx.tenant_id)
                .where(Assignment.employment_id == emp.id)
                .order_by(Assignment.effective_from.desc())  # type: ignore[attr-defined]
            )
        )
        .scalars()
        .first()
    )
    changes: dict[str, Any] = {}
    for key, kind, attr, column in (
        ("department", "DEPARTMENT", "org_unit_id", "org_unit_id"),
        ("location", "LOCATION", "location_id", "location_id"),
        ("designation", "DESIGNATION", "job_id", "job_id"),
    ):
        value = getattr(body, key)
        if value:
            changes[attr] = str(
                await resolve(
                    ctx, kind, value, legal_entity_id=emp.legal_entity_id, settings=settings
                )
            )
        elif last is not None:
            changes[attr] = str(getattr(last, column))
        else:
            raise SyncError(422, f"{key} is required to rehire", "FIELD_REQUIRED", {"field": key})
    manager_id = await _manager_employment(ctx, body.manager_external_id)
    if manager_id:
        changes["manager_employment_id"] = str(manager_id)
    pa = await _personnel_action(ctx, emp, PersonnelActionType.REHIRE, body.hire_date, changes)
    account = await _load_account(ctx, emp.id)
    if account is not None and account.status != "ACTIVE":
        account.status = "ACTIVE"
        ctx.session.add(account)
    await _touch_source(ctx, external_id, body.source_updated_at)
    return SyncResult(
        outcome="APPLIED" if pa.status == PersonnelActionStatus.APPLIED else "SCHEDULED",
        external_id=external_id,
        employment_id=to_typed_id("employment", emp.id),
        employee_code=emp.employee_number,
        changes={"hire_date": {"old": None, "new": body.hire_date.isoformat()}},
    )


async def _touch_source(ctx: IntegrationContext, external_id: str, src: datetime | None) -> None:
    await ctx.session.execute(
        text("""
        UPDATE external_identities
        SET last_source_updated_at =
                GREATEST(last_source_updated_at, CAST(:src AS timestamptz)),
            updated_at = now()
        WHERE tenant_id = :tid AND app_id = :app AND external_id = :ext
    """),
        {"tid": ctx.tenant_id, "app": ctx.app_id, "ext": external_id, "src": src},
    )


# ─── Upsert entry point ──────────────────────────────────────────────────────


async def upsert_employee(
    ctx: IntegrationContext, external_id: str, body: EmployeeUpsert
) -> SyncResult:
    ctx.require("employees.sync")
    await lock_external(ctx, external_id)
    ctx.session.info["integration_origin_app_id"] = ctx.app_id
    identity = await find_identity(ctx, external_id)
    if identity is None:
        return await create_employee(ctx, external_id, body)
    if body.employment_id and to_uuid(body.employment_id) != identity["employment_id"]:
        raise SyncError(409, "This external ID is linked to a different employee", "ALREADY_LINKED")
    return await update_employee(ctx, external_id, body)


def request_hash(payload: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

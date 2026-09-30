"""
HRMS Enterprise Data Migration Script
Imports legacy user and employee records from Suraj Group (EXIM) and RABS (Sharanga)
directly into normalized HRMS relational schema.

Usage:
    uv run python scripts/migrate_tenants.py --dry-run
    uv run python scripts/migrate_tenants.py --tenant suraj
    uv run python scripts/migrate_tenants.py --tenant rabs
    uv run python scripts/migrate_tenants.py --tenant all

Safe to re-run. After the import HRMS is the system of record (docs/erp-integration-plan.md
option A), so a re-run only ADDS what is missing and fills blanks:
  - it never changes an existing account's password, status or role;
  - it never rewrites hire dates, employment state or assignment history;
  - `--overwrite-existing` lets it correct profile fields, but only on accounts nobody has
    signed in to or changed the password of yet (i.e. before go-live) — real users' data is
    never touched.
A dry run walks the exact same code path and rolls back, so its created/updated/skipped
counts are what a real run would do.

Access: least privilege by construction. Ordinary staff get the EMPLOYEE role with SELF
scope; managers DIRECT_REPORTS; HR and accountants their own company; only the legacy
"admin" role becomes SUPER_ADMIN (all companies) and the run summary lists every one of
those for review. Legacy role names are matched EXACTLY against a table — anything unknown
is imported as a plain employee and reported, never guessed at.

Runs as the database owner (settings.database_url), which bypasses row-level security —
that is what lets one script write into two tenants. Nothing here is safe to point at a
database you don't own.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hrms.core.config import settings
from hrms.core.ids import to_typed_id
from hrms.core.security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration")

REPO_ROOT = Path(__file__).resolve().parents[2]

FAKE_EMAILS = {
    "abc@gmail.com",
    "test@gmail.com",
    "punit@alluvium.in",
    "dipakkumarharjibhai@gmail.com",
    "surajsudhakaran1994@gmail.com",
    "anubhavanand714@gmail.com",
    "uday@alluvium.in",
    "dipaksngh5@gmail.com",
}

BCRYPT_HASH = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")


def uid() -> UUID:
    return uuid4()


# ─── Cleaning helpers ────────────────────────────────────────────────────────


def clean_name(first: str, last: str) -> tuple[str, str]:
    given = re.sub(r"\s+", " ", (first or "").strip()).title()
    family = re.sub(r"\s+", " ", (last or "").strip()).title()
    if not given and not family:
        given = "Employee"
    elif not given:
        given, family = family, ""
    return given, family


def clean_phone(val: str | None) -> str | None:
    if not val:
        return None
    digits = re.sub(r"\D", "", str(val))
    if len(digits) == 10:
        return digits
    if len(digits) > 10 and digits.startswith("91") and len(digits) == 12:
        return digits[2:]
    return digits[:20] if digits else None


def clean_aadhaar(val: str | None) -> str | None:
    if not val:
        return None
    digits = re.sub(r"\D", "", str(val))
    return digits if len(digits) == 12 else None


def clean_pan(val: str | None) -> str | None:
    if not val:
        return None
    val = val.strip().upper()
    return val if len(val) == 10 else None


def clean_blood_group(val: str | None) -> str | None:
    if not val:
        return None
    val = val.strip().upper()
    val = re.sub(r"\s+POSITIVE", "+", val)
    val = re.sub(r"\s+NEGATIVE", "-", val)
    if val in {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}:
        return val
    junk = ["natus", "lorem", "molestias", "tempora"]
    if len(val) <= 10 and not any(w in val.lower() for w in junk):
        return val
    return None


def parse_date(val: Any, default: date | None = None) -> date | None:
    if not val:
        return default
    if isinstance(val, dict) and "$date" in val:
        val = val["$date"]
    val_str = str(val).strip()
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%y-%m-%d",
        "%d-%m-%y",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            pass
    return default


def source_id(record: dict) -> str | None:
    """Mongo `_id` is `{"$oid": "..."}` in these exports; accept a bare string too."""
    raw = record.get("_id")
    value = raw.get("$oid") if isinstance(raw, dict) else raw
    return str(value) if value else None


def tokens(*texts: str | None) -> set[str]:
    """Lower-case whole words, so "hr" matches "HR_Executive" but never "shrinkage"."""
    found: set[str] = set()
    for value in texts:
        found.update(t for t in re.split(r"[^a-z0-9]+", (value or "").lower()) if t)
    return found


def initial_password(first_name: str) -> str:
    """The documented Sharanga scheme (docs/erp-integration-plan.md §6): Firstname@1234, or HRMS_INITIAL_PASSWORD."""
    default_pw = os.environ.get("HRMS_INITIAL_PASSWORD")
    if default_pw:
        return default_pw
    alpha = re.sub(r"\W", "", first_name) or "User"
    return f"{alpha.capitalize()}@1234"


# ─── Mapping legacy roles onto HRMS roles ────────────────────────────────────


@dataclass(frozen=True)
class Access:
    role_name: str
    scope_type: str  # ALL | LEGAL_ENTITY | DIRECT_REPORTS | SELF
    job: str
    department: str


# scope_type is what the ROLE is allowed to be scoped to — see core/authz.SELF_SERVICE_ONLY_ROLES.
# Ordinary staff are SELF (their own record only); a manager sees their reports; only HR and
# accountants are given a whole company; the legacy "admin" is the only group-wide role.
SURAJ_KNOWN_ROLES = {
    "admin": Access("SUPER_ADMIN", "ALL", "Director", "Management"),
    "hr": Access("HR_MANAGER", "LEGAL_ENTITY", "HR Executive", "Human Resources"),
    "head_of_department": Access("MANAGER", "DIRECT_REPORTS", "Head of Department", "Operations"),
    "account": Access("ACCOUNTANT", "LEGAL_ENTITY", "Accountant", "Finance & Accounts"),
}
SURAJ_EMPLOYEE = Access("EMPLOYEE", "SELF", "Operations Executive", "Operations")
# Legacy roles that are ordinary staff (or, for "driver", not part of the HR import) — anything
# outside this and SURAJ_KNOWN_ROLES is imported as a plain employee AND reported.
SURAJ_STAFF_ROLES = {"user", "operation", "driver", ""}


def map_suraj_role(legacy_role: str | None) -> tuple[Access, bool]:
    """(access, recognised). Exact match on the whole legacy role — no substring guessing."""
    key = (legacy_role or "").strip().lower()
    if key in SURAJ_KNOWN_ROLES:
        return SURAJ_KNOWN_ROLES[key], True
    return SURAJ_EMPLOYEE, key in SURAJ_STAFF_ROLES


def map_rabs_role(role: str | None, department: str | None) -> Access:
    """Sharanga's roles are "Department_Job title" strings; match whole words in them."""
    words = tokens(role)
    dept_words = tokens(department)
    if {"super", "admin"} <= words:
        return Access("SUPER_ADMIN", "ALL", "Director", "Management")
    if "hr" in words or "hr" in dept_words:
        return Access("HR_MANAGER", "LEGAL_ENTITY", "HR Executive", "Human Resources")
    if any(w.startswith("account") for w in words | dept_words):
        return Access("ACCOUNTANT", "LEGAL_ENTITY", "Accountant", "Finance & Accounts")
    if words & {"head", "manager", "supervisor"}:
        job = "Production Supervisor" if "supervisor" in words else "Production Manager"
        return Access("MANAGER", "DIRECT_REPORTS", job, "Production")
    if "qc" in words or "qc" in dept_words:
        return Access("EMPLOYEE", "SELF", "QC Engineer", "Quality Control")
    if "operator" in words:
        return Access("EMPLOYEE", "SELF", "Machine Operator", "Production")
    if "helper" in words:
        return Access("EMPLOYEE", "SELF", "Helper", "Production")
    return Access("EMPLOYEE", "SELF", "Executive", "Production")


# ─── One source record, normalised ───────────────────────────────────────────


@dataclass
class ImportRecord:
    erp_system: str  # EXIM | SHARANGA
    erp_user_id: str
    employee_code: str
    first_name: str
    last_name: str
    email: str | None
    mobile: str | None
    password_hash: str | None
    must_change_password: bool
    is_active: bool
    dob: date | None
    gender: str | None
    hire_date: date
    separation_date: date | None
    service_stage: str
    worker_type: str
    entity_id: UUID
    access: Access
    kyc: dict[str, Any] = field(default_factory=dict)
    kyc_status: str = "SUBMITTED"
    kyc_verified_at: date | None = None

    @property
    def employment_state(self) -> str:
        return "ACTIVE" if self.is_active else "SEPARATED"

    @property
    def account_status(self) -> str:
        return "ACTIVE" if self.is_active else "INACTIVE"


def build_suraj_record(u: dict, entity_id: UUID, hash_pw=hash_password) -> ImportRecord | None:
    erp_id = source_id(u)
    code = (u.get("username") or "").strip()
    if not erp_id or not code:
        return None
    first, last = clean_name(u.get("first_name", ""), u.get("last_name", ""))
    raw_email = (u.get("email") or "").strip().lower()
    is_active = u.get("isActive") is not False
    legacy_hash = u.get("password")
    if isinstance(legacy_hash, str) and BCRYPT_HASH.match(legacy_hash):
        password_hash, must_change = legacy_hash, False
    else:
        # Not a usable bcrypt hash: an unguessable placeholder, and the user must be reset by HR.
        password_hash, must_change = hash_pw(uuid4().hex), True
    access, _ = map_suraj_role(u.get("role"))

    def part(*keys):
        joined = ", ".join(str(u[k]).strip() for k in keys if u.get(k) and str(u[k]).strip())
        return joined[:500] if joined else None

    emergency_name = (u.get("emergency_contact_name") or "").strip() or None
    marital = (u.get("marital_status") or "").strip().title() or None
    approved = str(u.get("kyc_approval")).lower() == "approved"
    return ImportRecord(
        erp_system="EXIM",
        erp_user_id=erp_id,
        employee_code=code,
        first_name=first,
        last_name=last,
        email=None if (not raw_email or raw_email in FAKE_EMAILS) else raw_email,
        mobile=clean_phone(u.get("mobile")),
        password_hash=password_hash,
        must_change_password=must_change,
        is_active=is_active,
        dob=parse_date(u.get("dob")),
        gender=None,
        hire_date=parse_date(u.get("joining_date"), default=date(2020, 1, 1)),
        separation_date=parse_date(u.get("deactivatedAt")) if not is_active else None,
        service_stage="PERMANENT",
        worker_type="PERMANENT",
        entity_id=entity_id,
        access=access,
        kyc={
            "pan_number": clean_pan(u.get("pan_no")),
            "aadhaar_number": clean_aadhaar(u.get("aadhar_no")),
            "pf_number": (u.get("pf_no") or "").strip() or None,
            "esi_number": (u.get("esic_no") or u.get("ESINo") or "").strip() or None,
            "bank_name": (u.get("bank_name") or "").strip() or None,
            "account_number": (u.get("bank_account_no") or "").strip() or None,
            "ifsc_code": (u.get("ifsc_code") or "").strip().upper() or None,
            "current_address": part(
                "communication_address_line_1",
                "communication_address_line_2",
                "communication_address_area",
                "communication_address_city",
                "communication_address_state",
                "communication_address_pincode",
            ),
            "permanent_address": part(
                "permanent_address_line_1",
                "permanent_address_line_2",
                "permanent_address_area",
                "permanent_address_city",
                "permanent_address_state",
                "permanent_address_pincode",
            ),
            "emergency_contact_name": emergency_name[:100] if emergency_name else None,
            "emergency_contact_phone": clean_phone(u.get("emergency_contact")),
            "marital_status": marital[:20] if marital else None,
            "blood_group": clean_blood_group(u.get("blood_group")),
        },
        kyc_status="VERIFIED" if approved else "SUBMITTED",
        kyc_verified_at=parse_date(u.get("kyc_date")) if approved else None,
    )


def build_rabs_record(
    login: dict, profile: dict | None, entity_id: UUID, hash_pw=hash_password
) -> ImportRecord | None:
    erp_id = source_id(login)
    code = (login.get("emp_id") or "").strip()
    if not erp_id or not code:
        return None
    info = (profile or {}).get("user_info") or {}
    raw_name = info.get("full_name") or login.get("full_name") or "Employee"
    parts = raw_name.split()
    first, last = clean_name(parts[0] if parts else "Employee", " ".join(parts[1:]))
    raw_email = (login.get("email") or info.get("email") or "").strip().lower()
    is_deleted = bool(login.get("is_deleted", False))
    access = map_rabs_role(login.get("role"), info.get("department"))
    deleted_at = (profile or {}).get("deleted_at") or login.get("deleted_at")
    address = (info.get("address") or "").strip()
    marital = (info.get("marital_status") or "").strip().title() or None
    stage = (info.get("employees_role") or "Permanent").upper()
    return ImportRecord(
        erp_system="SHARANGA",
        erp_user_id=erp_id,
        employee_code=code,
        first_name=first,
        last_name=last,
        email=raw_email if raw_email and "@" in raw_email else None,
        mobile=clean_phone(login.get("username")) or clean_phone(info.get("phone")),
        # Sharanga's own hashes are pbkdf2 — not portable. Everyone starts on the documented
        # initial password and is forced to replace it at first sign-in.
        password_hash=hash_pw(initial_password(first)),
        must_change_password=True,
        is_active=not is_deleted,
        dob=parse_date(info.get("dob")),
        gender=(info.get("gender") or "").strip().upper() or None,
        hire_date=parse_date((profile or {}).get("created_at"), default=date(2021, 1, 1)),
        separation_date=parse_date(deleted_at) if (is_deleted and deleted_at) else None,
        service_stage=stage,
        worker_type=stage,
        entity_id=entity_id,
        access=access,
        kyc={
            "aadhaar_number": clean_aadhaar(info.get("aadhaar_number")),
            "account_number": (info.get("salary_account_number") or "").strip() or None,
            "current_address": address[:500] or None,
            "emergency_contact_phone": clean_phone(info.get("emergency_contact_number")),
            "blood_group": clean_blood_group(info.get("blood_group")),
            "marital_status": marital[:20] if marital else None,
        },
        kyc_status="SUBMITTED",
    )


# ─── Database work ───────────────────────────────────────────────────────────


@dataclass
class Context:
    session: Any
    tenant_id: UUID
    overwrite: bool
    jobs: dict[str, UUID]
    roles: dict[str, UUID]
    stats: dict[str, Any]
    # legal entity -> (its location, {department name: org unit id})
    entity_dirs: dict[UUID, tuple[UUID, dict[str, UUID]]] = field(default_factory=dict)


async def setup_org_structure(
    session, tenant_id: UUID, entity_id: UUID, entity_name: str, entity_code: str, is_factory=False
):
    """Ensure canonical location, company org unit, and standard departments exist."""
    params = {"tid": str(tenant_id), "eid": str(entity_id)}
    loc = (
        await session.execute(
            text(
                "SELECT id FROM locations WHERE tenant_id = :tid AND legal_entity_id = :eid LIMIT 1"
            ),
            params,
        )
    ).fetchone()
    if loc:
        location_id = loc[0]
    else:
        location_id = uid()
        await session.execute(
            text("""
                INSERT INTO locations
                    (tenant_id, id, name, type, city, country_code, timezone, legal_entity_id,
                     status)
                VALUES (:tid, :id, :name, :type, 'Ahmedabad', 'IN', 'Asia/Kolkata', :eid, 'ACTIVE')
            """),
            {
                **params,
                "id": str(location_id),
                "name": f"{entity_name} {'Plant' if is_factory else 'Head Office'}",
                "type": "PLANT" if is_factory else "OFFICE",
            },
        )

    company = (
        await session.execute(
            text("""
                SELECT id FROM org_units
                WHERE tenant_id = :tid AND legal_entity_id = :eid AND type = 'COMPANY' LIMIT 1
            """),
            params,
        )
    ).fetchone()
    if company:
        company_ou_id = company[0]
    else:
        company_ou_id = uid()
        await session.execute(
            text("""
                INSERT INTO org_units
                    (tenant_id, id, name, code, type, legal_entity_id, effective_from, status)
                VALUES (:tid, :id, :name, :code, 'COMPANY', :eid, '2015-01-01', 'ACTIVE')
            """),
            {
                **params,
                "id": str(company_ou_id),
                "name": entity_name,
                "code": entity_code[:10].upper(),
            },
        )

    departments = (
        [
            "Production",
            "Quality Control",
            "Maintenance",
            "Finance & Accounts",
            "Human Resources",
            "Store & Warehouse",
            "Management",
        ]
        if is_factory
        else [
            "Operations",
            "Finance & Accounts",
            "Human Resources",
            "Management",
            "General Administration",
        ]
    )
    dept_map: dict[str, UUID] = {}
    for name in departments:
        found = (
            await session.execute(
                text("""
                    SELECT id FROM org_units
                    WHERE tenant_id = :tid AND legal_entity_id = :eid AND name = :name LIMIT 1
                """),
                {**params, "name": name},
            )
        ).fetchone()
        if found:
            dept_map[name] = found[0]
            continue
        dept_id = uid()
        await session.execute(
            text("""
                INSERT INTO org_units
                    (tenant_id, id, name, code, type, parent_id, legal_entity_id,
                     effective_from, status)
                VALUES (:tid, :id, :name, :code, 'DEPARTMENT', :parent, :eid, '2015-01-01',
                        'ACTIVE')
            """),
            {
                **params,
                "id": str(dept_id),
                "name": name,
                "code": f"{entity_code[:3].upper()}-{name[:3].upper()}",
                "parent": str(company_ou_id),
            },
        )
        dept_map[name] = dept_id
    return location_id, company_ou_id, dept_map


async def ensure_jobs(session, tenant_id: UUID, job_titles: list[str]) -> dict[str, UUID]:
    """Ensure canonical Job records exist for tenant."""
    job_map: dict[str, UUID] = {}
    for title in job_titles:
        row = (
            await session.execute(
                text("SELECT id FROM jobs WHERE tenant_id = :tid AND title = :title LIMIT 1"),
                {"tid": str(tenant_id), "title": title},
            )
        ).fetchone()
        if row:
            job_map[title] = row[0]
            continue
        job_id = uid()
        await session.execute(
            text(
                "INSERT INTO jobs (tenant_id, id, title, status) "
                "VALUES (:tid, :id, :title, 'ACTIVE')"
            ),
            {"tid": str(tenant_id), "id": str(job_id), "title": title},
        )
        job_map[title] = job_id
    return job_map


async def get_roles(session, tenant_id: UUID) -> dict[str, UUID]:
    res = await session.execute(
        text("SELECT name, id FROM roles WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
    )
    return {r[0]: r[1] for r in res.fetchall()}


async def _find_existing(ctx: Context, rec: ImportRecord):
    """(row, conflict). Deterministic: source id first, then employee code — never a guess."""
    tid = str(ctx.tenant_id)
    by_source = (
        (
            await ctx.session.execute(
                text("""
                    SELECT id, employment_id, last_login_at, password_changed_at
                    FROM user_accounts
                    WHERE tenant_id = :tid AND erp_system = :sys AND erp_user_id = :eid
                """),
                {"tid": tid, "sys": rec.erp_system, "eid": rec.erp_user_id},
            )
        )
        .mappings()
        .first()
    )
    if by_source:
        return by_source, None
    by_code = (
        (
            await ctx.session.execute(
                text("""
                    SELECT id, employment_id, last_login_at, password_changed_at,
                           erp_system, erp_user_id
                    FROM user_accounts
                    WHERE tenant_id = :tid AND lower(employee_code) = lower(:code)
                """),
                {"tid": tid, "code": rec.employee_code},
            )
        )
        .mappings()
        .all()
    )
    if len(by_code) > 1:
        return None, f"employee code {rec.employee_code!r} matches several existing accounts"
    if by_code:
        row = by_code[0]
        if row["erp_user_id"] and (row["erp_system"], row["erp_user_id"]) != (
            rec.erp_system,
            rec.erp_user_id,
        ):
            return None, (
                f"employee code {rec.employee_code!r} already belongs to a different source record"
            )
        return row, None  # a manually created account with this code: adopt it
    return None, None


async def _email_owner(ctx: Context, email: str) -> UUID | None:
    """Who holds this address in ANY tenant — email is globally unique across tenants."""
    return (
        await ctx.session.execute(
            text("SELECT id FROM user_accounts WHERE lower(email) = lower(:e) LIMIT 1"),
            {"e": email},
        )
    ).scalar()


async def _upsert_kyc(ctx: Context, rec: ImportRecord, employment_id: UUID, person_id: UUID) -> int:
    """Create the KYC record, or fill its blanks. Returns how many rows changed."""
    values = {k: v for k, v in rec.kyc.items() if v}
    if not values:
        return 0
    tid, eid = str(ctx.tenant_id), str(employment_id)
    existing = (
        await ctx.session.execute(
            text(
                "SELECT id FROM employee_kyc_records "
                "WHERE tenant_id = :tid AND employment_id = :eid"
            ),
            {"tid": tid, "eid": eid},
        )
    ).fetchone()
    if existing:
        # Fill blanks only: whatever HR or the employee has since entered stays.
        sets = ", ".join(f"{k} = COALESCE({k}, CAST(:{k} AS varchar))" for k in values)
        blanks = " OR ".join(f"{k} IS NULL" for k in values)
        result = await ctx.session.execute(
            text(
                f"UPDATE employee_kyc_records SET {sets} "
                f"WHERE tenant_id = :tid AND id = :kid AND ({blanks})"
            ),
            {**values, "tid": tid, "kid": str(existing[0])},
        )
        return result.rowcount or 0
    columns = ["tenant_id", "id", "employment_id", "person_id", "status", *values]
    binds = [":tid", ":id", ":eid", ":pid", ":status", *(f":{k}" for k in values)]
    params = {
        **values,
        "tid": tid,
        "id": str(uid()),
        "eid": eid,
        "pid": str(person_id),
        "status": rec.kyc_status,
    }
    if rec.kyc_status == "VERIFIED":
        columns.append("verified_at")
        binds.append(":verified_at")
        params["verified_at"] = datetime.combine(
            rec.kyc_verified_at or date.today(), datetime.min.time(), tzinfo=UTC
        )
    await ctx.session.execute(
        text(
            f"INSERT INTO employee_kyc_records ({', '.join(columns)}) VALUES ({', '.join(binds)})"
        ),
        params,
    )
    return 1


async def _create(ctx: Context, rec: ImportRecord) -> None:
    s, tid = ctx.session, str(ctx.tenant_id)
    location_id, dept_map = ctx.entity_dirs[rec.entity_id]
    dept_id = dept_map.get(rec.access.department) or next(iter(dept_map.values()))
    person_id, employment_id = uid(), uid()
    await s.execute(
        text("""
            INSERT INTO persons
                (tenant_id, id, legal_first_name, legal_last_name, date_of_birth, gender,
                 nationality)
            VALUES (:tid, :id, :f, :l, :dob, :gender, 'IN')
        """),
        {
            "tid": tid,
            "id": str(person_id),
            "f": rec.first_name,
            "l": rec.last_name,
            "dob": rec.dob,
            "gender": rec.gender,
        },
    )
    await s.execute(
        text("""
            INSERT INTO employments
                (tenant_id, id, person_id, legal_entity_id, employee_number, hire_date,
                 separation_date, employment_state, service_stage)
            VALUES (:tid, :id, :pid, :eid, :num, :hire, :sep, :state, :stage)
        """),
        {
            "tid": tid,
            "id": str(employment_id),
            "pid": str(person_id),
            "eid": str(rec.entity_id),
            "num": rec.employee_code,
            "hire": rec.hire_date,
            "sep": rec.separation_date,
            "state": rec.employment_state,
            "stage": rec.service_stage,
        },
    )
    await s.execute(
        text("""
            INSERT INTO assignments
                (tenant_id, id, employment_id, effective_from, org_unit_id, location_id, job_id,
                 worker_type)
            VALUES (:tid, :id, :emp, :hire, :ou, :loc, :job, :worker)
        """),
        {
            "tid": tid,
            "id": str(uid()),
            "emp": str(employment_id),
            "hire": rec.hire_date,
            "ou": str(dept_id),
            "loc": str(location_id),
            "job": str(ctx.jobs[rec.access.job]),
            "worker": rec.worker_type,
        },
    )
    account_id = uid()
    await s.execute(
        text("""
            INSERT INTO user_accounts
                (tenant_id, id, email, mobile, employee_code, password_hash, must_change_password,
                 employment_id, status, erp_system, erp_user_id)
            VALUES (:tid, :id, :email, :mobile, :code, :pw, :must, :emp, :status, :sys, :eid)
        """),
        {
            "tid": tid,
            "id": str(account_id),
            "email": rec.email,
            "mobile": rec.mobile,
            "code": rec.employee_code,
            "pw": rec.password_hash,
            "must": rec.must_change_password,
            "emp": str(employment_id),
            "status": rec.account_status,
            "sys": rec.erp_system,
            "eid": rec.erp_user_id,
        },
    )
    scope_value = (
        json.dumps([to_typed_id("legal_entity", rec.entity_id)])
        if rec.access.scope_type == "LEGAL_ENTITY"
        else None
    )
    await s.execute(
        text("""
            INSERT INTO role_assignments
                (tenant_id, id, user_account_id, role_id, scope_type, scope_value)
            VALUES (:tid, :id, :uid, :rid, :st, :sv)
        """),
        {
            "tid": tid,
            "id": str(uid()),
            "uid": str(account_id),
            "rid": str(ctx.roles[rec.access.role_name]),
            "st": rec.access.scope_type,
            "sv": scope_value,
        },
    )
    await _upsert_kyc(ctx, rec, employment_id, person_id)


async def _update_existing(ctx: Context, rec: ImportRecord, row) -> str:
    """Returns 'updated' or 'unchanged'. Blanks are filled; nothing already set is replaced."""
    s, tid = ctx.session, str(ctx.tenant_id)
    account_id, employment_id = str(row["id"]), row["employment_id"]
    in_use = row["last_login_at"] is not None or row["password_changed_at"] is not None
    may_overwrite = ctx.overwrite and not in_use
    if ctx.overwrite and in_use:
        ctx.stats["overwrite_skipped_in_use"] += 1

    changed = 0
    result = await s.execute(
        text("""
            UPDATE user_accounts
            SET email = COALESCE(email, CAST(:email AS varchar)),
                mobile = COALESCE(mobile, CAST(:mobile AS varchar)),
                employee_code = COALESCE(employee_code, CAST(:code AS varchar)),
                erp_system = COALESCE(erp_system, CAST(:sys AS varchar)),
                erp_user_id = COALESCE(erp_user_id, CAST(:eid AS varchar))
            WHERE tenant_id = :tid AND id = :id
              AND ((email IS NULL AND CAST(:email AS varchar) IS NOT NULL)
                   OR (mobile IS NULL AND CAST(:mobile AS varchar) IS NOT NULL)
                   OR (employee_code IS NULL AND CAST(:code AS varchar) IS NOT NULL)
                   OR (erp_system IS NULL AND CAST(:sys AS varchar) IS NOT NULL)
                   OR (erp_user_id IS NULL AND CAST(:eid AS varchar) IS NOT NULL))
        """),
        {
            "tid": tid,
            "id": account_id,
            "email": rec.email,
            "mobile": rec.mobile,
            "code": rec.employee_code,
            "sys": rec.erp_system,
            "eid": rec.erp_user_id,
        },
    )
    changed += result.rowcount or 0

    if may_overwrite:
        # Before go-live only: correct the account to what the source says.
        await s.execute(
            text("""
                UPDATE user_accounts
                SET email = COALESCE(:email, email), mobile = COALESCE(:mobile, mobile),
                    password_hash = :pw, must_change_password = :must, status = :status
                WHERE tenant_id = :tid AND id = :id
            """),
            {
                "tid": tid,
                "id": account_id,
                "email": rec.email,
                "mobile": rec.mobile,
                "pw": rec.password_hash,
                "must": rec.must_change_password,
                "status": rec.account_status,
            },
        )
        changed += 1

    if employment_id:
        person = (
            await s.execute(
                text("SELECT person_id FROM employments WHERE tenant_id = :tid AND id = :eid"),
                {"tid": tid, "eid": str(employment_id)},
            )
        ).fetchone()
        if person:
            result = await s.execute(
                text("""
                    UPDATE persons
                    SET date_of_birth = COALESCE(date_of_birth, CAST(:dob AS date)),
                        gender = COALESCE(gender, CAST(:g AS varchar))
                    WHERE tenant_id = :tid AND id = :pid
                      AND ((date_of_birth IS NULL AND CAST(:dob AS date) IS NOT NULL)
                           OR (gender IS NULL AND CAST(:g AS varchar) IS NOT NULL))
                """),
                {"tid": tid, "pid": str(person[0]), "dob": rec.dob, "g": rec.gender},
            )
            changed += result.rowcount or 0
            changed += await _upsert_kyc(ctx, rec, employment_id, person[0])
        if may_overwrite:
            await s.execute(
                text("""
                    UPDATE employments
                    SET hire_date = :hire, separation_date = :sep, employment_state = :state
                    WHERE tenant_id = :tid AND id = :eid
                """),
                {
                    "tid": tid,
                    "eid": str(employment_id),
                    "hire": rec.hire_date,
                    "sep": rec.separation_date,
                    "state": rec.employment_state,
                },
            )
            # Only a single, still-original assignment may be re-dated; a recorded history
            # (transfers, promotions) is never rewritten.
            await s.execute(
                text("""
                    UPDATE assignments SET effective_from = :hire
                    WHERE tenant_id = :tid AND employment_id = :eid
                      AND (SELECT count(*) FROM assignments
                           WHERE tenant_id = :tid AND employment_id = :eid) = 1
                """),
                {"tid": tid, "eid": str(employment_id), "hire": rec.hire_date},
            )
            changed += 1
    return "updated" if changed else "unchanged"


async def import_record(ctx: Context, rec: ImportRecord) -> None:
    """One record, one savepoint: a failure is reported and never poisons the rest of the run."""
    stats = ctx.stats
    try:
        async with ctx.session.begin_nested():
            row, conflict = await _find_existing(ctx, rec)
            if conflict:
                stats["conflicts"].append({"source_id": rec.erp_user_id, "reason": conflict})
                return
            if rec.email:
                holder = await _email_owner(ctx, rec.email)
                if holder is not None and (row is None or holder != row["id"]):
                    # The same address already belongs to another account (typically the same
                    # person in the other company). Import without it: they can still sign in
                    # by employee code or mobile, and HR can set an address later.
                    stats["email_conflicts"].append(rec.employee_code)
                    rec.email = None
            if row is None:
                await _create(ctx, rec)
                stats["created_users"] += 1
            else:
                outcome = await _update_existing(ctx, rec, row)
                stats["updated_users" if outcome == "updated" else "unchanged_users"] += 1
        stats["by_role"][rec.access.role_name] = stats["by_role"].get(rec.access.role_name, 0) + 1
        if rec.access.role_name == "SUPER_ADMIN":
            stats["super_admins"].append(rec.employee_code)
    except Exception as exc:  # noqa: BLE001 - reported below, run decides what to do
        logger.error("Record %s (%s) failed: %s", rec.employee_code, rec.erp_user_id, exc)
        stats["errors"].append(
            {"source_id": rec.erp_user_id, "error": f"{type(exc).__name__}: {exc}"}
        )


def new_stats(**extra) -> dict[str, Any]:
    return {
        "created_users": 0,
        "updated_users": 0,
        "unchanged_users": 0,
        "overwrite_skipped_in_use": 0,
        "conflicts": [],
        "email_conflicts": [],
        "errors": [],
        "by_role": {},
        "super_admins": [],
        "unrecognised_legacy_roles": {},
        # company (as written in the source) -> users skipped because its legal entity is missing
        "unmatched_companies": {},
        **extra,
    }


def duplicate_report(records: list[ImportRecord]) -> dict[str, int]:
    """Identifiers shared by several accounts of one tenant (a shared phone, a repeated code)."""
    report = {}
    for label, values in (
        ("duplicate_mobiles", [r.mobile for r in records if r.mobile]),
        ("duplicate_employee_codes", [r.employee_code.lower() for r in records]),
        ("duplicate_emails", [r.email for r in records if r.email]),
    ):
        seen: dict[str, int] = {}
        for value in values:
            seen[value] = seen.get(value, 0) + 1
        report[label] = sum(1 for n in seen.values() if n > 1)
    return report


# ─── Tenant importers ────────────────────────────────────────────────────────


def _load(path: Path):
    if not path.exists():
        raise SystemExit(f"Source file not found: {path} (use --data-dir)")
    with open(path) as f:
        return json.load(f)


async def migrate_suraj(session, tenant_id: UUID, data_dir: Path, overwrite: bool) -> dict:
    """Migrate the usable Suraj Group users from exim.users.json."""
    logger.info("Starting Suraj Group migration...")
    raw_users = _load(data_dir / "exim.users.json")

    entities = {
        r[1]: r[0]
        for r in (
            await session.execute(
                text("SELECT id, name FROM legal_entities WHERE tenant_id = :tid"),
                {"tid": str(tenant_id)},
            )
        ).fetchall()
    }
    logger.info("Loaded %d legal entities for Suraj Group", len(entities))

    # Legacy company strings -> HRMS legal entity names
    name_map = {
        "suraj forwarders & shipping agencies": "Suraj Forwarders & Shipping Agencies",
        "suraj forwarders private limited": "Suraj Forwarders Private Limited",
        "suraj forwarders": "Suraj Forwarders Private Limited",  # merged with the Pvt Ltd entity
        "sr container carriers": "SR Container Carriers",
        "novusha consulting services india llp": "Novusha Consulting Services India LLP",
        "sansar tradelink": "Sansar Tradelink",
        "eximbiz enterprise": "EXIMBIZ Enterprise",
        "alluvium iot solutions private limited": "Alluvium IoT Solutions Private Limited",
        "paramount propack private limited": "Paramount Propack Private Limited",
    }

    entity_dirs: dict[UUID, tuple[UUID, dict[str, UUID]]] = {}
    for entity_name, entity_id in entities.items():
        code = "".join(w[0] for w in entity_name.split() if w.isalnum())
        loc_id, _, depts = await setup_org_structure(
            session, tenant_id, entity_id, entity_name, code, is_factory=False
        )
        entity_dirs[entity_id] = (loc_id, depts)

    job_titles = sorted({a.job for a in SURAJ_KNOWN_ROLES.values()} | {SURAJ_EMPLOYEE.job})
    stats = new_stats(
        total_source=len(raw_users),
        excluded_rabs=0,
        excluded_blank_company=0,
        excluded_demo=0,
        usable=0,
        entities_breakdown={},
    )
    ctx = Context(
        session=session,
        tenant_id=tenant_id,
        overwrite=overwrite,
        jobs=await ensure_jobs(session, tenant_id, job_titles),
        roles=await get_roles(session, tenant_id),
        stats=stats,
        entity_dirs=entity_dirs,
    )

    records: list[ImportRecord] = []
    for u in raw_users:
        company = (u.get("company") or "").strip().lower()
        if not company:
            stats["excluded_blank_company"] += 1
        elif "rabs" in company:
            stats["excluded_rabs"] += 1
        elif "demo" in company:
            stats["excluded_demo"] += 1
        else:
            target = name_map.get(company)
            if not target or target not in entities:
                # A setup problem, not one bad record: the company's legal entity has to exist
                # first. Counted, reported once per company below, and it blocks a real run.
                stats["unmatched_companies"][company] = (
                    stats["unmatched_companies"].get(company, 0) + 1
                )
                continue
            rec = build_suraj_record(u, entities[target])
            if rec is None:
                stats["errors"].append({"source_id": source_id(u), "error": "missing _id/username"})
                continue
            _, recognised = map_suraj_role(u.get("role"))
            if not recognised:
                legacy = (u.get("role") or "").strip()
                stats["unrecognised_legacy_roles"][legacy] = (
                    stats["unrecognised_legacy_roles"].get(legacy, 0) + 1
                )
            stats["usable"] += 1
            stats["entities_breakdown"][target] = stats["entities_breakdown"].get(target, 0) + 1
            records.append(rec)

    if stats["unmatched_companies"]:
        skipped = sum(stats["unmatched_companies"].values())
        missing = sorted({name_map[c] for c in stats["unmatched_companies"] if c in name_map})
        unmapped = sorted(c for c in stats["unmatched_companies"] if c not in name_map)
        if missing:
            logger.warning(
                "%d user(s) skipped because their company has no legal entity in this tenant. "
                "Create these legal entities first, named exactly: %s",
                skipped,
                "; ".join(missing),
            )
        if unmapped:
            logger.warning("Companies missing from the mapping table (name_map): %s", unmapped)

    stats["duplicate_identifiers"] = duplicate_report(records)
    for rec in records:
        await import_record(ctx, rec)
    return stats


async def migrate_rabs(session, tenant_id: UUID, data_dir: Path, overwrite: bool) -> dict:
    """Migrate the Sharanga / RABS accounts (logins joined to profiles on emp_id)."""
    logger.info("Starting RABS / Sharanga migration...")
    logins = _load(data_dir / "Sharanga_Production.login.json")
    profiles = _load(data_dir / "Sharanga_Production.employee_profiles.json")
    profile_map = {p.get("emp_id"): p for p in profiles if p.get("emp_id")}

    row = (
        await session.execute(
            text("SELECT id, name FROM legal_entities WHERE tenant_id = :tid LIMIT 1"),
            {"tid": str(tenant_id)},
        )
    ).fetchone()
    if not row:
        raise SystemExit("The RABS tenant has no legal entity — create one first.")
    entity_id, entity_name = row[0], row[1]
    loc_id, _, dept_map = await setup_org_structure(
        session, tenant_id, entity_id, entity_name, "RABS", is_factory=True
    )
    job_titles = [
        "Helper",
        "Machine Operator",
        "Quality Inspector",
        "QC Engineer",
        "Production Supervisor",
        "Production Manager",
        "Accountant",
        "HR Executive",
        "Director",
        "Executive",
    ]
    stats = new_stats(
        total_logins=len(logins),
        joined_profiles=0,
        system_accounts=0,
        active_users=0,
        inactive_users=0,
    )
    ctx = Context(
        session=session,
        tenant_id=tenant_id,
        overwrite=overwrite,
        jobs=await ensure_jobs(session, tenant_id, job_titles),
        roles=await get_roles(session, tenant_id),
        stats=stats,
        entity_dirs={entity_id: (loc_id, dept_map)},
    )

    records: list[ImportRecord] = []
    for login in logins:
        emp_id = (login.get("emp_id") or "").strip()
        profile = profile_map.get(emp_id)
        stats["joined_profiles" if profile else "system_accounts"] += 1
        rec = build_rabs_record(login, profile, entity_id)
        if rec is None:
            stats["errors"].append({"source_id": source_id(login), "error": "missing _id/emp_id"})
            continue
        stats["active_users" if rec.is_active else "inactive_users"] += 1
        records.append(rec)

    stats["duplicate_identifiers"] = duplicate_report(records)
    for rec in records:
        await import_record(ctx, rec)
    return stats


async def record_batch(session, tenant_id: UUID, source_system: str, total: int, stats: dict):
    await session.execute(
        text("""
            INSERT INTO import_batches
                (tenant_id, id, source_system, imported_at, imported_by, total_records,
                 created_records, updated_records, is_dry_run, details)
            VALUES (:tid, :id, :source, :at, 'migration_script', :total, :created, :updated,
                    false, CAST(:details AS jsonb))
        """),
        {
            "tid": str(tenant_id),
            "id": str(uid()),
            "source": source_system,
            "at": datetime.now(UTC),
            "total": total,
            "created": stats["created_users"],
            "updated": stats["updated_users"],
            "details": json.dumps(stats, default=str),
        },
    )


async def resolve_tenant(session, ref: str) -> tuple[UUID, str]:
    """A tenant UUID or slug -> (id, display name); fails clearly if it doesn't exist."""
    try:
        clause, value = "id = CAST(:v AS uuid)", str(UUID(ref))
    except ValueError:
        clause, value = "slug = :v", ref
    row = (
        await session.execute(
            text(f"SELECT id, display_name FROM tenants WHERE {clause}"), {"v": value}
        )
    ).fetchone()
    if not row:
        raise SystemExit(f"No tenant matches {ref!r} — create it first (Platform Console).")
    return row[0], row[1]


def problem_count(stats: dict) -> int:
    """Source records that were NOT imported and need attention."""
    return (
        len(stats["errors"]) + len(stats["conflicts"]) + sum(stats["unmatched_companies"].values())
    )


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HRMS Tenant Data Migration")
    parser.add_argument("--tenant", choices=["suraj", "rabs", "all"], default="all")
    parser.add_argument(
        "--dry-run", action="store_true", help="Run everything, report, and roll back"
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Correct existing records from the source — only accounts nobody has signed in to",
    )
    parser.add_argument(
        "--allow-partial", action="store_true", help="Commit even if some records failed"
    )
    parser.add_argument(
        "--yes", action="store_true", help="Don't ask for confirmation before a real run"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=REPO_ROOT, help="Folder holding the JSON exports"
    )
    # No defaults: tenants are created in the Platform Console, so their ids differ per environment.
    parser.add_argument(
        "--suraj-tenant", help="Tenant (UUID or slug) that receives the Suraj Group users"
    )
    parser.add_argument(
        "--rabs-tenant", help="Tenant (UUID or slug) that receives the Sharanga users"
    )
    args = parser.parse_args(argv)
    for which, ref in (("suraj", args.suraj_tenant), ("rabs", args.rabs_tenant)):
        if args.tenant in (which, "all") and not ref:
            parser.error(f"--{which}-tenant <slug-or-uuid> is required to import {which}")

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    exit_code = 0
    async with Session() as session, session.begin():
        targets = []
        for which, ref, source, importer in (
            ("suraj", args.suraj_tenant, "EXIM", migrate_suraj),
            ("rabs", args.rabs_tenant, "SHARANGA", migrate_rabs),
        ):
            if args.tenant in (which, "all"):
                tenant_id, display_name = await resolve_tenant(session, ref)
                targets.append((tenant_id, display_name, source, importer))

        if not args.dry_run and not args.yes:
            print("This will WRITE to the database for:")
            for _, name, source, _ in targets:
                print(f"  - {name}  ({source})")
            if input("Type 'import' to continue: ").strip() != "import":
                print("Aborted — nothing was changed.")
                return 1

        all_stats = []
        for tenant_id, display_name, source, importer in targets:
            stats = await importer(session, tenant_id, args.data_dir, args.overwrite_existing)
            all_stats.append((tenant_id, source, stats))
            logger.info("%s result:\n%s", display_name, json.dumps(stats, indent=2, default=str))
            if stats["super_admins"]:
                logger.warning(
                    "%d account(s) become SUPER_ADMIN with access to every company — review: %s",
                    len(stats["super_admins"]),
                    stats["super_admins"],
                )
            if stats["unrecognised_legacy_roles"]:
                logger.warning(
                    "Legacy roles with no explicit mapping (imported as plain employees): %s",
                    stats["unrecognised_legacy_roles"],
                )

        failed = sum(problem_count(s) for _, _, s in all_stats)
        if args.dry_run:
            logger.info("DRY RUN COMPLETE — rolling back, no changes committed.")
            await session.rollback()
        elif failed and not args.allow_partial:
            logger.error(
                "%d record(s) were not imported (errors, conflicts, or a company with no legal "
                "entity) — rolling back everything. Fix them, or re-run with --allow-partial to "
                "commit the rest.",
                failed,
            )
            await session.rollback()
            exit_code = 2
        else:
            for tenant_id, source, stats in all_stats:
                total = stats.get("usable", stats.get("total_logins", 0))
                await record_batch(session, tenant_id, source, total, stats)
            logger.info("MIGRATION COMMITTED SUCCESSFULLY!")
    await engine.dispose()
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

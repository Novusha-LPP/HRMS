"""
Platform kernel — Tenant and User/Role tables.

The tenant table lives in the public schema and is NOT row-level-secured
(it is the root of the isolation boundary, not inside it).
User accounts and roles are tenant-scoped.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Column, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"

    id: UUID = Field(primary_key=True)
    slug: str = Field(max_length=63, unique=True, index=True)
    display_name: str = Field(max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    country_code: str = Field(max_length=2, default="IN")
    status: str = Field(default="ACTIVE", max_length=50)
    plan: str = Field(default="STARTER", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = Field(default=None)


class UserAccount(SQLModel, table=True):
    __tablename__ = "user_accounts"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    email: str | None = Field(default=None, max_length=320, index=True)
    # For employees without email: code + mobile OTP login
    employee_code: str | None = Field(default=None, max_length=50)
    mobile: str | None = Field(default=None, max_length=20)
    # bcrypt hash (core/security.py). Null means the account cannot log in with
    # a password yet (e.g. provisioned but not activated).
    password_hash: str | None = Field(default=None, max_length=255)
    # Set for freshly imported accounts and after an admin reset: every endpoint
    # except change-password is refused until the user picks their own password.
    must_change_password: bool = Field(default=False)
    password_changed_at: datetime | None = Field(default=None)
    # Every token carries the epoch it was issued under (claim "ep"); a password
    # change or reset bumps it, so all earlier tokens stop working at once (see
    # core/database.get_session).
    token_epoch: int = Field(default=0)
    # The employment this login IS — drives "my dashboard", "my leave", etc.
    # Separate from role_assignments, which grant visibility into OTHER
    # employees' data (a shared accountant, a group HR manager, ...).
    employment_id: UUID | None = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_login_at: datetime | None = Field(default=None)
    version: int = Field(default=0)
    erp_system: str | None = Field(default=None, max_length=20)
    erp_user_id: str | None = Field(default=None, max_length=100)


class AuthThrottle(SQLModel, table=True):
    """
    Attempt counters for login / registration (core/throttle.py). No tenant_id
    and no RLS: they're consulted before anyone is identified, and keys are
    stored only as SHA-256 hashes.
    """

    __tablename__ = "auth_throttle"

    scope: str = Field(primary_key=True, max_length=40)
    key_hash: str = Field(primary_key=True, max_length=64)
    failures: int = Field(default=0)
    window_started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    locked_until: datetime | None = Field(default=None)


class ApiKey(SQLModel, table=True):
    """Server-to-server ERP credentials (hashed at rest; not yet wired to an endpoint)."""

    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_hash", "key_hash", unique=True),)

    tenant_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
        )
    )
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=120)
    key_prefix: str = Field(max_length=20)
    key_hash: str = Field(max_length=64)
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column("scopes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    )
    allowed_ips: list[str] | None = Field(default=None, sa_column=Column("allowed_ips", JSONB))
    is_active: bool = Field(default=True)
    expires_at: datetime | None = Field(default=None)
    rate_limit_per_minute: int = Field(default=600)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = Field(default=None)
    last_used_at: datetime | None = Field(default=None)
    last_used_ip: str | None = Field(default=None, max_length=45)
    total_requests: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False, server_default="0")
    )


class ImportBatch(SQLModel, table=True):
    """One run of an ERP import script (scripts/migrate_tenants.py): what was created/updated."""

    __tablename__ = "import_batches"

    tenant_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
        )
    )
    id: UUID = Field(primary_key=True)
    source_system: str = Field(max_length=50)
    imported_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    imported_by: str = Field(default="system_migration", max_length=100)
    total_records: int = Field(default=0)
    created_records: int = Field(default=0)
    updated_records: int = Field(default=0)
    is_dry_run: bool = Field(default=False)
    details: dict[str, Any] | None = Field(default=None, sa_column=Column("details", JSONB))


class Role(SQLModel, table=True):
    __tablename__ = "roles"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_system: bool = Field(default=False)
    version: int = Field(default=0)


class PlatformAdmin(SQLModel, table=True):
    """
    Above every tenant, not inside one — no tenant_id, no RLS (see migration
    0006). Its login issues a distinctly-typed JWT so it can never be mixed
    up with a tenant-scoped user_accounts login.
    """

    __tablename__ = "platform_admins"

    id: UUID = Field(primary_key=True)
    email: str = Field(max_length=320, unique=True, index=True)
    name: str = Field(max_length=255)
    password_hash: str = Field(max_length=255)
    # ADMIN = full read/write. VIEWER = read-only support tier — can see
    # every tenant/admin but every mutating endpoint rejects it.
    role: str = Field(default="ADMIN", max_length=50)
    status: str = Field(default="ACTIVE", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_login_at: datetime | None = Field(default=None)


class PlatformAuditLog(SQLModel, table=True):
    """
    Who did what, on the platform, and when. Write-once — nothing ever
    updates or deletes a row here. actor_admin_id is nullable (not that
    anything currently writes a null actor) so a future system-initiated
    action wouldn't need a schema change.
    """

    __tablename__ = "platform_audit_log"

    id: UUID = Field(primary_key=True)
    actor_admin_id: UUID | None = Field(default=None, foreign_key="platform_admins.id")
    actor_name: str = Field(max_length=255)
    action: str = Field(max_length=100)
    target_type: str = Field(max_length=50)
    target_id: UUID | None = Field(default=None)
    target_label: str = Field(max_length=255)
    metadata_json: dict[str, Any] | None = Field(
        default=None, sa_column=Column("metadata_json", JSONB)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PlatformPasswordResetToken(SQLModel, table=True):
    __tablename__ = "platform_password_reset_tokens"

    id: UUID = Field(primary_key=True)
    admin_id: UUID = Field(foreign_key="platform_admins.id")
    token_hash: str = Field(max_length=64, unique=True)
    expires_at: datetime = Field()
    used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RoleAssignment(SQLModel, table=True):
    __tablename__ = "role_assignments"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    user_account_id: UUID = Field()
    role_id: UUID = Field()
    # Data scope: which org units / employees are visible
    scope_type: str = Field(default="ALL", max_length=50)
    scope_value: str | None = Field(default=None, max_length=500)
    granted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = Field(default=None)

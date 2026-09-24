"""
Platform kernel — Tenant and User/Role tables.

The tenant table lives in the public schema and is NOT row-level-secured
(it is the root of the isolation boundary, not inside it).
User accounts and roles are tenant-scoped.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlmodel import Field, SQLModel
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"

    id: UUID = Field(primary_key=True)
    slug: str = Field(max_length=63, unique=True, index=True)
    display_name: str = Field(max_length=255)
    industry: Optional[str] = Field(default=None, max_length=100)
    country_code: str = Field(max_length=2, default="IN")
    status: str = Field(default="ACTIVE", max_length=50)
    plan: str = Field(default="STARTER", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    archived_at: Optional[datetime] = Field(default=None)


class UserAccount(SQLModel, table=True):
    __tablename__ = "user_accounts"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    email: Optional[str] = Field(default=None, max_length=320, index=True)
    # For employees without email: code + mobile OTP login
    employee_code: Optional[str] = Field(default=None, max_length=50)
    mobile: Optional[str] = Field(default=None, max_length=20)
    # bcrypt hash (passlib). Null means the account cannot log in with a
    # password yet (e.g. provisioned but not activated).
    password_hash: Optional[str] = Field(default=None, max_length=255)
    # The employment this login IS — drives "my dashboard", "my leave", etc.
    # Separate from role_assignments, which grant visibility into OTHER
    # employees' data (a shared accountant, a group HR manager, ...).
    employment_id: Optional[UUID] = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: Optional[datetime] = Field(default=None)
    version: int = Field(default=0)


class Role(SQLModel, table=True):
    __tablename__ = "roles"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: Optional[datetime] = Field(default=None)


class PlatformAuditLog(SQLModel, table=True):
    """
    Who did what, on the platform, and when. Write-once — nothing ever
    updates or deletes a row here. actor_admin_id is nullable (not that
    anything currently writes a null actor) so a future system-initiated
    action wouldn't need a schema change.
    """
    __tablename__ = "platform_audit_log"

    id: UUID = Field(primary_key=True)
    actor_admin_id: Optional[UUID] = Field(default=None, foreign_key="platform_admins.id")
    actor_name: str = Field(max_length=255)
    action: str = Field(max_length=100)
    target_type: str = Field(max_length=50)
    target_id: Optional[UUID] = Field(default=None)
    target_label: str = Field(max_length=255)
    metadata_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column("metadata_json", JSONB))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlatformPasswordResetToken(SQLModel, table=True):
    __tablename__ = "platform_password_reset_tokens"

    id: UUID = Field(primary_key=True)
    admin_id: UUID = Field(foreign_key="platform_admins.id")
    token_hash: str = Field(max_length=64, unique=True)
    expires_at: datetime = Field()
    used_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RoleAssignment(SQLModel, table=True):
    __tablename__ = "role_assignments"

    tenant_id: UUID = Field(foreign_key="tenants.id", primary_key=True)
    id: UUID = Field(primary_key=True)
    user_account_id: UUID = Field()
    role_id: UUID = Field()
    # Data scope: which org units / employees are visible
    scope_type: str = Field(default="ALL", max_length=50)
    scope_value: Optional[str] = Field(default=None, max_length=500)
    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None)

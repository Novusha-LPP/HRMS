from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

TenantStatus = Literal["ACTIVE", "SUSPENDED"]
AdminStatus = Literal["ACTIVE", "SUSPENDED"]


class PlatformLoginRequest(BaseModel):
    email: EmailStr
    password: str
    otp: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

class PlatformLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    name: str
    email: str
    role: str


class PlatformMe(BaseModel):
    mfa_required: bool = False
    name: str
    email: str
    role: str


class TenantSummary(BaseModel):
    id: str
    slug: str
    display_name: str
    status: str
    plan: str
    legal_entity_count: int
    created_at: datetime
    archived_at: datetime | None = None


class TenantListResponse(BaseModel):
    items: list[TenantSummary]
    total: int


class TenantLegalEntity(BaseModel):
    id: str
    name: str
    short_name: str | None = None
    status: str


class TenantDetail(TenantSummary):
    country_code: str
    employee_count: int
    legal_entities: list[TenantLegalEntity]


class TenantUpdate(BaseModel):
    status: TenantStatus | None = None
    plan: Literal["STARTER", "GROWTH", "ENTERPRISE"] | None = None


class PlatformCompanyCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=255)
    country_code: str = Field(default="IN", min_length=2, max_length=2)
    mode: Literal["NEW_TENANT", "SUBSIDIARY"]
    # Required for SUBSIDIARY: which existing tenant this becomes a legal
    # entity inside. Ignored for NEW_TENANT.
    parent_tenant_id: str | None = None
    # Required for NEW_TENANT: the first login for that new, independent
    # tenant. Ignored for SUBSIDIARY — it inherits the parent tenant's
    # existing admins/roles rather than getting its own.
    admin_email: EmailStr | None = None
    admin_password: str | None = Field(default=None, min_length=8, max_length=72)


class PlatformCompanyResponse(BaseModel):
    mode: Literal["NEW_TENANT", "SUBSIDIARY"]
    tenant_id: str
    tenant_name: str
    legal_entity_id: str
    legal_entity_name: str
    admin_email: str | None = None


class PlatformAdminSummary(BaseModel):
    id: str
    name: str
    email: str
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None = None
    is_you: bool = False


class PlatformAdminCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: Literal["ADMIN", "VIEWER"] = "ADMIN"


class PlatformAdminUpdate(BaseModel):
    status: AdminStatus | None = None
    role: Literal["ADMIN", "VIEWER"] | None = None


class AuditLogEntry(BaseModel):
    id: str
    actor_name: str
    action: str
    target_type: str
    target_id: str | None = None
    target_label: str
    metadata: dict[str, Any] | None = None
    created_at: datetime


class AuditLogResponse(BaseModel):
    items: list[AuditLogEntry]
    total: int


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    # Only populated when HRMS_DEBUG=true — there's no email provider wired
    # up in this codebase, so dev/test flows need some way to get the link.
    # Never populated outside debug mode.
    dev_reset_url: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=72)

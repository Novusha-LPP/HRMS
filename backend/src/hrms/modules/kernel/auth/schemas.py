from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from hrms.core.security import password_fits_bcrypt


def check_password_bytes(value: str) -> str:
    """Schemas count characters; bcrypt counts bytes (a 30-emoji password is 120)."""
    if not password_fits_bcrypt(value):
        raise ValueError("Password is too long (at most 72 bytes; non-ASCII characters count more)")
    return value


class LoginRequest(BaseModel):
    """
    `identifier` is an email address, employee code or mobile number. The legacy
    payload keys (email / username / phone / mobile / user / emp_id) are still
    accepted so existing clients keep working.
    """

    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(max_length=256)
    otp: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    # Company code (the tenant's slug). Only needed when the same employee code or
    # mobile number exists in more than one company — the API then answers
    # COMPANY_REQUIRED and the sign-in form asks for it.
    tenant: str | None = Field(default=None, max_length=63)

    @model_validator(mode="before")
    @classmethod
    def normalize_identifier(cls, data: Any) -> Any:
        if isinstance(data, dict) and "identifier" not in data:
            for key in ("email", "username", "phone", "mobile", "user", "emp_id"):
                if data.get(key):
                    return {**data, "identifier": str(data[key]).strip()}
        return data


class TenantRegister(BaseModel):
    """
    Registering a brand-new company here means a brand-new TENANT — a
    completely separate isolation boundary from any existing tenant (e.g.
    SFPL Group), not another legal entity inside one. Adding a sister
    company to an existing group is POST /v1/org/legal-entities instead,
    which requires already being signed in as that tenant's admin.
    """

    company_name: str = Field(min_length=2, max_length=255)
    country_code: str = Field(default="IN", min_length=2, max_length=2)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=72)

    _password_bytes = field_validator("admin_password")(check_password_bytes)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=72)

    _password_bytes = field_validator("new_password")(check_password_bytes)


class LegalEntitySummary(BaseModel):
    id: str
    name: str


class MeResponse(BaseModel):
    mfa_required: bool = False
    id: str
    email: str | None
    name: str
    employment_id: str | None
    tenant_id: str
    tenant_name: str
    roles: list[str]
    permissions: list[str]
    is_all_scope: bool
    legal_entities: list[LegalEntitySummary]
    # True until the user has replaced an imported / admin-issued password.
    must_change_password: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: MeResponse

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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


class LegalEntitySummary(BaseModel):
    id: str
    name: str


class MeResponse(BaseModel):
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


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: MeResponse

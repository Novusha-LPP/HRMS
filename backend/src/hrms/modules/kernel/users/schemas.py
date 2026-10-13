from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from hrms.modules.kernel.auth.schemas import check_password_bytes

ScopeType = Literal["ALL", "LEGAL_ENTITY", "SELF", "DIRECT_REPORTS", "ALL_REPORTS"]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: str
    scope_type: ScopeType
    # Required when scope_type == "LEGAL_ENTITY" — typed legal_entity ids.
    legal_entity_ids: list[str] | None = None
    # Required when scope_type in (SELF, DIRECT_REPORTS, ALL_REPORTS): the
    # employee this login IS. Optional otherwise (an admin-only account with
    # no personal employment record, e.g. a company's HR admin login).
    employment_id: str | None = None
    # Ask the person to replace the password you chose at their first sign-in.
    must_change_password: bool = False
    # Why HR is setting an email a connected app owns for this employee (see
    # modules/integrations/ownership.py).
    override_reason: str | None = Field(default=None, max_length=300)

    _password_bytes = field_validator("password")(check_password_bytes)


class UserUpdate(BaseModel):
    """INACTIVE blocks sign-in (and every existing token) at once; ACTIVE restores it."""

    status: Literal["ACTIVE", "INACTIVE"]


class PasswordReset(BaseModel):
    """A temporary password. The user is made to replace it at their next sign-in."""

    password: str = Field(min_length=8, max_length=72)

    _password_bytes = field_validator("password")(check_password_bytes)


class SignInSlipsRequest(BaseModel):
    """Issue temporary sign-in details to employees, typically shop-floor staff without email."""

    employment_ids: list[str] = Field(min_length=1, max_length=100)
    # 8 digits, easy to type on a phone or kiosk; otherwise 10 letters and digits.
    numeric: bool = True


class SignInSlip(BaseModel):
    employment_id: str
    employee_number: str
    name: str
    company: str | None = None
    outcome: Literal["CREATED", "RESET", "SKIPPED"]
    reason: str | None = None
    # Shown once, in this response only. Never stored in plain text or logged.
    temporary_password: str | None = None


class RoleResponse(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]


class UserResponse(BaseModel):
    id: str
    email: str | None = None
    status: str
    role: str
    scope_type: str
    legal_entity_ids: list[str] = []
    employment_id: str | None = None
    employee_name: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None
    # The linked employee's state, and whether this login can actually sign in
    # right now: an ACTIVE account belonging to a SEPARATED employee cannot.
    employment_state: str | None = None
    can_sign_in: bool = True
    must_change_password: bool = False

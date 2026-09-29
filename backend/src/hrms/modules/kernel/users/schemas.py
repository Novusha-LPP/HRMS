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

    _password_bytes = field_validator("password")(check_password_bytes)


class UserUpdate(BaseModel):
    """INACTIVE blocks sign-in (and every existing token) at once; ACTIVE restores it."""

    status: Literal["ACTIVE", "INACTIVE"]


class PasswordReset(BaseModel):
    """A temporary password. The user is made to replace it at their next sign-in."""

    password: str = Field(min_length=8, max_length=72)

    _password_bytes = field_validator("password")(check_password_bytes)


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

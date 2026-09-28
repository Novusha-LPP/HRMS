from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

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

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

ScopeType = Literal["ALL", "LEGAL_ENTITY", "SELF", "DIRECT_REPORTS", "ALL_REPORTS"]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: str
    scope_type: ScopeType
    # Required when scope_type == "LEGAL_ENTITY" — typed legal_entity ids.
    legal_entity_ids: Optional[list[str]] = None
    # Required when scope_type in (SELF, DIRECT_REPORTS, ALL_REPORTS): the
    # employee this login IS. Optional otherwise (an admin-only account with
    # no personal employment record, e.g. a company's HR admin login).
    employment_id: Optional[str] = None


class RoleResponse(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: list[str]


class UserResponse(BaseModel):
    id: str
    email: Optional[str] = None
    status: str
    role: str
    scope_type: str
    legal_entity_ids: list[str] = []
    employment_id: Optional[str] = None
    employee_name: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None

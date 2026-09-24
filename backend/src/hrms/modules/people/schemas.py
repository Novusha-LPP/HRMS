from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from hrms.modules.people.models import (
    EmploymentState,
    PersonnelActionStatus,
    PersonnelActionType,
)


class PersonCreate(BaseModel):
    legal_first_name: str = Field(max_length=100)
    legal_last_name: str = Field(max_length=100)
    preferred_name: Optional[str] = Field(default=None)
    date_of_birth: Optional[date] = Field(default=None)
    gender: Optional[str] = Field(default=None)
    nationality: Optional[str] = Field(default=None, max_length=2)


class PersonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "per_..."
    legal_first_name: str
    legal_last_name: str
    preferred_name: Optional[str]
    date_of_birth: Optional[date]
    gender: Optional[str]
    version: int


class MyProfileResponse(BaseModel):
    id: str  # typed: "per_..."
    # Legal name isn't included here — changing it is an HR/documentation
    # matter, not self-service (see update_my_profile in router.py).
    legal_first_name: str
    legal_last_name: str
    preferred_name: Optional[str]
    date_of_birth: Optional[date]
    gender: Optional[str]
    nationality: Optional[str]
    email: Optional[str]
    mobile: Optional[str]
    version: int


class MyProfileUpdate(BaseModel):
    """
    Every field optional and unset-vs-null aware (PATCH semantics via
    model_dump(exclude_unset=True) in the router) — sending a field clears
    it to null, omitting it leaves the current value untouched.
    """
    preferred_name: Optional[str] = Field(default=None, max_length=100)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=20)
    nationality: Optional[str] = Field(default=None, max_length=2)
    mobile: Optional[str] = Field(default=None, max_length=20)


# ──────────────────────────────────────────────────────────────────────────────

class EmploymentCreate(BaseModel):
    person_id: str  # typed ID
    legal_entity_id: str  # typed ID
    employee_number: str = Field(max_length=50)
    hire_date: date
    service_stage: Optional[str] = Field(default=None)


class EmploymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "emp_..."
    person_id: str
    legal_entity_id: str
    employee_number: str
    hire_date: date
    separation_date: Optional[date]
    employment_state: EmploymentState
    service_stage: Optional[str]
    version: int
    # From the employee's current (open) assignment, if one has been placed
    # yet — null for an employment that's been created but not yet HIREd
    # into a department (see POST /v1/personnel-actions).
    legal_entity_name: Optional[str] = None
    org_unit_id: Optional[str] = None
    department: Optional[str] = None
    job_id: Optional[str] = None
    designation: Optional[str] = None
    location_id: Optional[str] = None
    location: Optional[str] = None
    manager_employment_id: Optional[str] = None
    manager_name: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────

class PersonnelActionCreate(BaseModel):
    """
    POST /v1/personnel-actions — the only write path for employment changes.
    """
    employment_id: str = Field(description="Typed employment ID (emp_...)")
    type: PersonnelActionType
    reason_code: Optional[str] = Field(default=None)
    effective_date: date
    changes: Optional[dict[str, Any]] = Field(
        default=None,
        description="Fields being changed and their new values. Keys are typed IDs where applicable.",
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Client-generated key; duplicate requests with the same key return the original response.",
    )


class PersonnelActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "pa_..."
    employment_id: str
    type: PersonnelActionType
    reason_code: Optional[str]
    effective_date: date
    status: PersonnelActionStatus
    changes: Optional[dict[str, Any]]
    version: int


class PersonnelActionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: PersonnelActionType
    effective_date: date
    status: PersonnelActionStatus
    submitted_at: Optional[datetime]

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hrms.core.versioning import version_field
from hrms.modules.people.models import (
    EmploymentState,
    PersonnelActionStatus,
    PersonnelActionType,
)


class PersonCreate(BaseModel):
    legal_first_name: str = Field(max_length=100)
    legal_last_name: str = Field(max_length=100)
    preferred_name: str | None = Field(default=None)
    date_of_birth: date | None = Field(default=None)
    gender: str | None = Field(default=None)
    nationality: str | None = Field(default=None, max_length=2)


class PersonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "per_..."
    legal_first_name: str
    legal_last_name: str
    preferred_name: str | None
    date_of_birth: date | None
    gender: str | None
    version: int


class MyProfileResponse(BaseModel):
    id: str  # typed: "per_..."
    # Legal name isn't included here — changing it is an HR/documentation
    # matter, not self-service (see update_my_profile in router.py).
    legal_first_name: str
    legal_last_name: str
    preferred_name: str | None
    date_of_birth: date | None
    gender: str | None
    nationality: str | None
    email: str | None
    mobile: str | None
    version: int


class MyProfileUpdate(BaseModel):
    """
    Every field optional and unset-vs-null aware (PATCH semantics via
    model_dump(exclude_unset=True) in the router) — sending a field clears
    it to null, omitting it leaves the current value untouched.
    """

    preferred_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=2)
    mobile: str | None = Field(default=None, max_length=20)
    version: int | None = version_field()


# ──────────────────────────────────────────────────────────────────────────────


class EmploymentCreate(BaseModel):
    person_id: str  # typed ID
    legal_entity_id: str  # typed ID
    # Omit to auto-generate from the company's (or tenant's) employee ID
    # scheme, if one is configured — see org/models.py:EmployeeIdScheme.
    # Required as before if no scheme exists.
    employee_number: str | None = Field(default=None, max_length=50)
    hire_date: date
    service_stage: str | None = Field(default=None)


class EmploymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "emp_..."
    person_id: str
    legal_entity_id: str
    employee_number: str
    hire_date: date
    separation_date: date | None
    employment_state: EmploymentState
    service_stage: str | None
    version: int
    date_of_birth: date | None = None
    gender: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    # From the employee's current (open) assignment, if one has been placed
    # yet — null for an employment that's been created but not yet HIREd
    # into a department (see POST /v1/personnel-actions).
    legal_entity_name: str | None = None
    org_unit_id: str | None = None
    department: str | None = None
    team_name: str | None = None
    job_id: str | None = None
    designation: str | None = None
    grade_id: str | None = None
    grade: str | None = None
    position_id: str | None = None
    position_title: str | None = None
    location_id: str | None = None
    location: str | None = None
    manager_employment_id: str | None = None
    manager_name: str | None = None


# ──────────────────────────────────────────────────────────────────────────────


class PersonnelActionCreate(BaseModel):
    """
    POST /v1/personnel-actions — the only write path for employment changes.
    """

    employment_id: str = Field(description="Typed employment ID (emp_...)")
    type: PersonnelActionType
    reason_code: str | None = Field(default=None)
    effective_date: date
    changes: dict[str, Any] | None = Field(
        default=None,
        description="Changed fields and new values; use typed IDs for references.",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Client-generated key for deduplicating requests.",
    )
    override_reason: str | None = Field(
        default=None,
        max_length=300,
        description="Why HR is changing a field a connected app owns (e.g. the department of "
        "an employee managed in the ERP). Required for such a change when the app's settings "
        "allow overrides.",
    )

    @field_validator("idempotency_key")
    @classmethod
    def _not_reserved(cls, value: str | None) -> str | None:
        # "int:" keys mark changes made through the sync API (modules/integrations/hooks.py).
        if value is not None and value.startswith("int:"):
            raise ValueError("Idempotency keys starting with 'int:' are reserved")
        return value


class PersonnelActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "pa_..."
    employment_id: str
    type: PersonnelActionType
    reason_code: str | None
    effective_date: date
    status: PersonnelActionStatus
    changes: dict[str, Any] | None
    version: int
    # Set when a scheduled action could not be applied on its date (status FAILED).
    failure_reason: str | None = None


class PersonnelActionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: PersonnelActionType
    effective_date: date
    status: PersonnelActionStatus
    submitted_at: datetime | None
    failure_reason: str | None = None
    reason_code: str | None = None
    changes: dict[str, Any] | None = None

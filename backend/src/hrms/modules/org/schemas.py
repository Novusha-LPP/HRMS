from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LegalEntityCreate(BaseModel):
    name: str = Field(max_length=255)
    short_name: str | None = Field(default=None, max_length=50)
    country_code: str = Field(default="IN", max_length=2)
    # None = inherit the tenant/deployment default (HRMS_DEFAULT_FINANCIAL_YEAR_START_MONTH).
    establishment_date: date | None = None
    financial_year_start_month: int | None = Field(default=None, ge=1, le=12)


class LegalEntityUpdate(BaseModel):
    """All fields optional — only what's sent gets changed (and audited)."""

    name: str | None = Field(default=None, max_length=255)
    short_name: str | None = Field(default=None, max_length=50)
    country_code: str | None = Field(default=None, max_length=2)
    establishment_date: date | None = None
    financial_year_start_month: int | None = Field(default=None, ge=1, le=12)


class LegalEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "le_..."
    name: str
    short_name: str | None
    country_code: str
    status: str
    version: int
    establishment_date: date | None = None
    financial_year_start_month: int | None = None


class LocationCreate(BaseModel):
    name: str = Field(max_length=255)
    type: str = Field(max_length=50)
    address_line1: str | None = Field(default=None)
    city: str | None = Field(default=None)
    state_code: str | None = Field(default=None)
    pincode: str | None = Field(default=None)
    country_code: str = Field(default="IN")
    timezone: str = Field(default="Asia/Kolkata")
    legal_entity_id: str | None = Field(default=None)


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    type: str | None = Field(default=None, max_length=50)
    head_employment_id: str | None = None
    lead_employment_id: str | None = None
    pm_employment_id: str | None = None
    address_line1: str | None = Field(default=None)
    city: str | None = Field(default=None)
    state_code: str | None = Field(default=None)
    pincode: str | None = Field(default=None)
    country_code: str | None = Field(default=None)
    timezone: str | None = Field(default=None)


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "loc_..."
    name: str
    type: str
    city: str | None
    state_code: str | None
    country_code: str
    timezone: str
    status: str
    version: int
    legal_entity_id: str | None = None


class OrgUnitCreate(BaseModel):
    name: str = Field(max_length=255)
    code: str | None = Field(default=None)
    type: str = Field(max_length=50)
    parent_id: str | None = Field(default=None)
    legal_entity_id: str | None = Field(default=None)
    location_id: str | None = Field(default=None)
    head_employment_id: str | None = None
    lead_employment_id: str | None = None
    pm_employment_id: str | None = None
    effective_from: date


class OrgUnitUpdate(BaseModel):
    """
    Renaming/recoding only — moving a unit to a different parent, company or
    location is a structural change, not covered here (create a new unit and
    migrate assignments, or ask for that as its own endpoint if it's needed).
    """

    name: str | None = Field(default=None, max_length=255)
    code: str | None = Field(default=None)
    type: str | None = Field(default=None, max_length=50)
    head_employment_id: str | None = None
    lead_employment_id: str | None = None
    pm_employment_id: str | None = None


class AssignDepartmentsRequest(BaseModel):
    department_ids: list[str] = Field(min_length=1, max_length=100)


class OrgUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "ou_..."
    name: str
    code: str | None
    type: str
    parent_id: str | None
    legal_entity_id: str | None = None
    department_template_id: str | None = None
    head_employment_id: str | None = None
    lead_employment_id: str | None = None
    pm_employment_id: str | None = None
    status: str
    effective_from: date
    effective_to: date | None
    version: int


class EmployeeIdSchemeCreate(BaseModel):
    # None = tenant-wide (every company shares this scheme); set = specific
    # to that one company.
    legal_entity_id: str | None = Field(default=None)
    prefix: str = Field(max_length=20)
    separator: str = Field(default="-", max_length=5)
    number_digits: int = Field(default=4, ge=1, le=10)
    # Where numbering starts — 1 by default, but an admin migrating from a
    # system that already issued IDs up to, say, 340 would set this to 341.
    next_number: int = Field(default=1, ge=1)


class EmployeeIdSchemeUpdate(BaseModel):
    prefix: str | None = Field(default=None, max_length=20)
    separator: str | None = Field(default=None, max_length=5)
    number_digits: int | None = Field(default=None, ge=1, le=10)
    next_number: int | None = Field(default=None, ge=1)


class EmployeeIdSchemeResponse(BaseModel):
    id: str  # typed: "eis_..."
    legal_entity_id: str | None = None
    legal_entity_name: str | None = None
    prefix: str
    separator: str
    number_digits: int
    next_number: int
    # What the *next* generated ID will look like, without consuming it —
    # for the admin UI to show a live preview while configuring.
    preview: str


class JobCreate(BaseModel):
    title: str = Field(max_length=255)
    code: str | None = Field(default=None)
    function: str | None = Field(default=None)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    code: str | None = Field(default=None)
    function: str | None = Field(default=None)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "job_..."
    title: str
    code: str | None
    function: str | None
    status: str
    version: int


MasterStatus = Literal["ACTIVE", "INACTIVE"]


class GradeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    # Rank order: lower comes first in pickers and reports (e.g. W1 < W2 < M1).
    sequence: int = Field(default=0, ge=0)


class GradeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    sequence: int | None = Field(default=None, ge=0)
    status: MasterStatus | None = None


class GradeResponse(BaseModel):
    id: str  # typed: "grd_..."
    code: str
    name: str
    sequence: int
    status: str
    version: int


class CostCentreCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)


class CostCentreUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: MasterStatus | None = None


class CostCentreResponse(BaseModel):
    id: str  # typed: "cc_..."
    code: str
    name: str
    status: str
    version: int


class PositionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=50)
    org_unit_id: str
    job_id: str | None = None
    grade_id: str | None = None
    # None = no limit: the position exists but doesn't count towards vacancies.
    max_headcount: int | None = Field(default=None, ge=1)
    effective_from: date | None = None  # defaults to today
    effective_to: date | None = None


class PositionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=50)
    job_id: str | None = None
    grade_id: str | None = None
    max_headcount: int | None = Field(default=None, ge=1)
    status: MasterStatus | None = None
    effective_to: date | None = None


class PositionResponse(BaseModel):
    id: str  # typed: "pos_..."
    title: str
    code: str | None
    org_unit_id: str
    org_unit_name: str | None
    legal_entity_id: str | None
    job_id: str | None
    job_title: str | None
    grade_id: str | None
    grade_name: str | None
    max_headcount: int | None
    # Current employees placed in this position; vacancies = max_headcount - filled.
    filled: int
    vacancies: int | None
    status: str
    effective_from: date
    effective_to: date | None
    version: int


class ChangeLogEntry(BaseModel):
    """One row of an entity's history — GET .../{id}/history."""

    id: str
    action: str
    changes: dict[str, dict[str, Any]]  # {"field": {"old": ..., "new": ...}}
    changed_by: str | None  # typed user_account id
    changed_by_name: str | None  # resolved live at read time — never stored
    changed_at: datetime

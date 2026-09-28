from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class LegalEntityCreate(BaseModel):
    name: str = Field(max_length=255)
    short_name: str | None = Field(default=None, max_length=50)
    country_code: str = Field(default="IN", max_length=2)


class LegalEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "le_..."
    name: str
    short_name: str | None
    country_code: str
    status: str
    version: int


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
    effective_from: date


class OrgUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "ou_..."
    name: str
    code: str | None
    type: str
    parent_id: str | None
    legal_entity_id: str | None = None
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


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "job_..."
    title: str
    code: str | None
    function: str | None
    status: str
    version: int

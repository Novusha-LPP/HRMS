from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LegalEntityCreate(BaseModel):
    name: str = Field(max_length=255)
    short_name: Optional[str] = Field(default=None, max_length=50)
    country_code: str = Field(default="IN", max_length=2)


class LegalEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "le_..."
    name: str
    short_name: Optional[str]
    country_code: str
    status: str
    version: int


class LocationCreate(BaseModel):
    name: str = Field(max_length=255)
    type: str = Field(max_length=50)
    address_line1: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    state_code: Optional[str] = Field(default=None)
    pincode: Optional[str] = Field(default=None)
    country_code: str = Field(default="IN")
    timezone: str = Field(default="Asia/Kolkata")
    legal_entity_id: Optional[str] = Field(default=None)


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "loc_..."
    name: str
    type: str
    city: Optional[str]
    state_code: Optional[str]
    country_code: str
    timezone: str
    status: str
    version: int
    legal_entity_id: Optional[str] = None


class OrgUnitCreate(BaseModel):
    name: str = Field(max_length=255)
    code: Optional[str] = Field(default=None)
    type: str = Field(max_length=50)
    parent_id: Optional[str] = Field(default=None)
    legal_entity_id: Optional[str] = Field(default=None)
    location_id: Optional[str] = Field(default=None)
    effective_from: date


class OrgUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "ou_..."
    name: str
    code: Optional[str]
    type: str
    parent_id: Optional[str]
    legal_entity_id: Optional[str] = None
    status: str
    effective_from: date
    effective_to: Optional[date]
    version: int


class JobCreate(BaseModel):
    title: str = Field(max_length=255)
    code: Optional[str] = Field(default=None)
    function: Optional[str] = Field(default=None)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # typed: "job_..."
    title: str
    code: Optional[str]
    function: Optional[str]
    status: str
    version: int

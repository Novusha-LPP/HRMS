from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from hrms.core.versioning import version_field
from hrms.modules.branding.models import AssetKind

Source = Literal["COMPANY", "GROUP", "DEFAULT"]
COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
WEBSITE_PATTERN = r"^(https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/\S*)?$"


def _blank_to_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class BrandAssetResponse(BaseModel):
    id: str  # "bast_..."
    kind: AssetKind
    file_name: str
    width: int
    height: int
    byte_size: int
    uploaded_at: datetime


class BrandProfileInput(BaseModel):
    """Every field: a value, or null to inherit (from the group, or the built-in default)."""

    logo_asset_id: str | None = None
    primary_color: str | None = Field(default=None, pattern=COLOR_PATTERN)
    accent_color: str | None = Field(default=None, pattern=COLOR_PATTERN)
    footer_text: str | None = Field(default=None, max_length=500)
    contact_email: str | None = Field(default=None, max_length=320, pattern=EMAIL_PATTERN)
    contact_phone: str | None = Field(default=None, max_length=30)
    website: str | None = Field(default=None, max_length=255, pattern=WEBSITE_PATTERN)
    # The version last read, or null when the row doesn't exist yet.
    version: int | None = version_field()

    _blank = field_validator(
        "logo_asset_id",
        "primary_color",
        "accent_color",
        "footer_text",
        "contact_email",
        "contact_phone",
        "website",
        mode="before",
    )(_blank_to_none)

    @field_validator("primary_color", "accent_color")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class BrandProfileResponse(BaseModel):
    id: str  # "brnd_..."
    legal_entity_id: str | None  # null: the group default
    logo: BrandAssetResponse | None
    primary_color: str | None
    accent_color: str | None
    footer_text: str | None
    contact_email: str | None
    contact_phone: str | None
    website: str | None
    version: int
    recorded_at: datetime


class ResolvedField(BaseModel):
    value: str | None
    source: Source


class ColorCheck(BaseModel):
    """How the primary colour prints: as given if readable on white, else darkened."""

    text_color: str
    adjusted: bool
    contrast: float


class CompanyDetails(BaseModel):
    name: str
    registered_name: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    cin: str | None = None
    pan: str | None = None
    tan: str | None = None
    gstin: str | None = None
    pf_establishment_code: str | None = None
    esic_employer_code: str | None = None


class ResolvedBranding(BaseModel):
    legal_entity_id: str | None
    company: CompanyDetails
    fields: dict[str, ResolvedField]
    logo: BrandAssetResponse | None
    color_check: ColorCheck


class SignatoryInput(BaseModel):
    legal_entity_id: str | None = None  # null: may sign for any company
    name: str = Field(min_length=1, max_length=120)
    designation: str | None = Field(default=None, max_length=120)
    signature_asset_id: str | None = None

    _blank = field_validator("legal_entity_id", "designation", "signature_asset_id", mode="before")(
        _blank_to_none
    )


class SignatoryUpdate(SignatoryInput):
    version: int | None = version_field()


class SignatoryResponse(BaseModel):
    id: str  # "sgn_..."
    legal_entity_id: str | None
    name: str
    designation: str | None
    signature: BrandAssetResponse | None
    version: int

"""
How documents look (migration 0075): logos, colours, footer, contact details and signatories,
set once for the group and per company where a company differs.

- BrandAsset: an uploaded logo or signature image, re-encoded to PNG and stored encrypted
  (core/document_store.py). Immutable: a payslip issued with an image can be reproduced.
- BrandProfile: legal_entity_id None is the group default. A company row overrides only the
  fields it sets; None means "inherit" (branding/resolve.py).
- DocumentSignatory: who signs documents, for one company or (legal_entity_id None) for any.
"""

import enum
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class AssetKind(enum.StrEnum):
    LOGO = "LOGO"
    SIGNATURE = "SIGNATURE"


class BrandAsset(SQLModel, table=True):
    __tablename__ = "brand_assets"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    kind: str = Field(max_length=20)
    file_name: str = Field(max_length=255)
    width: int
    height: int
    byte_size: int
    sha256: str = Field(max_length=64)
    storage_ref: str = Field(max_length=500)
    uploaded_by: UUID | None = Field(default=None)
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)


class BrandProfile(SQLModel, table=True):
    __tablename__ = "brand_profiles"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    legal_entity_id: UUID | None = Field(default=None)
    logo_asset_id: UUID | None = Field(default=None)
    primary_color: str | None = Field(default=None, max_length=7)
    accent_color: str | None = Field(default=None, max_length=7)
    footer_text: str | None = Field(default=None, max_length=500)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=30)
    website: str | None = Field(default=None, max_length=255)
    recorded_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    version: int = Field(default=0)


class DocumentSignatory(SQLModel, table=True):
    __tablename__ = "document_signatories"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    legal_entity_id: UUID | None = Field(default=None)
    name: str = Field(max_length=120)
    designation: str | None = Field(default=None, max_length=120)
    signature_asset_id: UUID | None = Field(default=None)
    recorded_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

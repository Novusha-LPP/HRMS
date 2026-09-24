"""
Organisation module — the structural dimensions of a tenant.

Every table has (tenant_id, id) as its composite primary key and is covered
by a PostgreSQL RLS policy that checks current_setting('app.tenant_id').

Effective dating uses (effective_from, effective_to) with effective_to = NULL
meaning the record is open / current.  A DB exclusion constraint prevents
overlapping slices per parent entity.
"""

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class LegalEntity(SQLModel, table=True):
    __tablename__ = "legal_entities"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=255)
    short_name: Optional[str] = Field(default=None, max_length=50)
    # TAN, PAN, CIN etc. stored as JSONB in a companion registrations table
    country_code: str = Field(max_length=2, default="IN")
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


class Location(SQLModel, table=True):
    __tablename__ = "locations"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=255)
    type: str = Field(max_length=50)  # OFFICE, SITE, PLANT, REMOTE, ...
    address_line1: Optional[str] = Field(default=None, max_length=255)
    address_line2: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    state_code: Optional[str] = Field(default=None, max_length=10)
    pincode: Optional[str] = Field(default=None, max_length=20)
    country_code: str = Field(max_length=2, default="IN")
    timezone: str = Field(default="Asia/Kolkata", max_length=50)
    # FK to legal_entity for statutory registrations
    legal_entity_id: Optional[UUID] = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


class OrgUnit(SQLModel, table=True):
    """
    Self-referencing tree.  Tenant defines the depth and meaning of each level
    (e.g. Company → Division → Department → Team).
    The closure table for fast ancestor/descendant queries is built separately.
    """
    __tablename__ = "org_units"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=255)
    code: Optional[str] = Field(default=None, max_length=50, index=True)
    type: str = Field(max_length=50)  # Tenant-defined: DIVISION, DEPARTMENT, TEAM, ...
    parent_id: Optional[UUID] = Field(default=None)
    legal_entity_id: Optional[UUID] = Field(default=None)
    location_id: Optional[UUID] = Field(default=None)
    cost_centre_id: Optional[UUID] = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=50)
    effective_from: date = Field()
    effective_to: Optional[date] = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    title: str = Field(max_length=255)
    code: Optional[str] = Field(default=None, max_length=50, index=True)
    function: Optional[str] = Field(default=None, max_length=100)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


class Grade(SQLModel, table=True):
    __tablename__ = "grades"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    code: str = Field(max_length=50, index=True)
    name: str = Field(max_length=100)
    sequence: int = Field(default=0)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)


class Position(SQLModel, table=True):
    __tablename__ = "positions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    title: str = Field(max_length=255)
    code: Optional[str] = Field(default=None, max_length=50)
    org_unit_id: UUID = Field()
    job_id: Optional[UUID] = Field(default=None)
    grade_id: Optional[UUID] = Field(default=None)
    max_headcount: Optional[int] = Field(default=None)
    status: str = Field(default="OPEN", max_length=50)
    effective_from: date = Field()
    effective_to: Optional[date] = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


class CostCentre(SQLModel, table=True):
    __tablename__ = "cost_centres"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    code: str = Field(max_length=50, index=True)
    name: str = Field(max_length=255)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

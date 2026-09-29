"""
Organisation module — the structural dimensions of a tenant.

Every table has (tenant_id, id) as its composite primary key and is covered
by a PostgreSQL RLS policy that checks current_setting('app.tenant_id').

Effective dating uses (effective_from, effective_to) with effective_to = NULL
meaning the record is open / current.  A DB exclusion constraint prevents
overlapping slices per parent entity.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class LegalEntity(SQLModel, table=True):
    __tablename__ = "legal_entities"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=255)
    short_name: str | None = Field(default=None, max_length=50)
    # TAN, PAN, CIN etc. stored as JSONB in a companion registrations table
    country_code: str = Field(max_length=2, default="IN")
    status: str = Field(default="ACTIVE", max_length=50)
    financial_year_start_month: int | None = Field(default=None, ge=1, le=12)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class Location(SQLModel, table=True):
    __tablename__ = "locations"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=255)
    type: str = Field(max_length=50)  # OFFICE, SITE, PLANT, REMOTE, ...
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state_code: str | None = Field(default=None, max_length=10)
    pincode: str | None = Field(default=None, max_length=20)
    country_code: str = Field(max_length=2, default="IN")
    timezone: str = Field(default="Asia/Kolkata", max_length=50)
    # FK to legal_entity for statutory registrations
    legal_entity_id: UUID | None = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


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
    code: str | None = Field(default=None, max_length=50, index=True)
    type: str = Field(max_length=50)  # Tenant-defined: DIVISION, DEPARTMENT, TEAM, ...
    parent_id: UUID | None = Field(default=None)
    legal_entity_id: UUID | None = Field(default=None)
    location_id: UUID | None = Field(default=None)
    cost_centre_id: UUID | None = Field(default=None)
    status: str = Field(default="ACTIVE", max_length=50)
    effective_from: date = Field()
    effective_to: date | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    title: str = Field(max_length=255)
    code: str | None = Field(default=None, max_length=50, index=True)
    function: str | None = Field(default=None, max_length=100)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class Grade(SQLModel, table=True):
    __tablename__ = "grades"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    code: str = Field(max_length=50, index=True)
    name: str = Field(max_length=100)
    sequence: int = Field(default=0)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class Position(SQLModel, table=True):
    __tablename__ = "positions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    title: str = Field(max_length=255)
    code: str | None = Field(default=None, max_length=50)
    org_unit_id: UUID = Field()
    job_id: UUID | None = Field(default=None)
    grade_id: UUID | None = Field(default=None)
    max_headcount: int | None = Field(default=None)
    status: str = Field(default="OPEN", max_length=50)
    effective_from: date = Field()
    effective_to: date | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class EmployeeIdScheme(SQLModel, table=True):
    """
    Configurable employee-number generation: prefix + zero-padded running
    number (e.g. "SFPL-0001"). legal_entity_id NULL means tenant-wide —
    every company shares one prefix and one counter; set means specific to
    that company, with its own independent counter. At most one active
    (non-archived) row per (tenant, legal_entity_id) and at most one active
    tenant-wide row are enforced by partial unique indexes (migration
    0015), not application logic, so a race between two admins can't leave
    two live schemes fighting over the same numbers.

    Resolution order in people/router.py: the hiring company's own scheme,
    then the tenant-wide one, then — if neither exists — employee_number
    must be supplied manually. This is opt-in: a tenant that's always
    typed employee numbers by hand keeps doing that until an admin sets a
    scheme up.
    """

    __tablename__ = "employee_id_schemes"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    legal_entity_id: UUID | None = Field(default=None, index=True)
    prefix: str = Field(max_length=20)
    separator: str = Field(default="-", max_length=5)
    number_digits: int = Field(default=4, ge=1, le=10)
    # The NEXT number to be issued — incremented atomically on each use
    # (UPDATE ... RETURNING, see people/router.py), never read-then-written
    # non-atomically.
    next_number: int = Field(default=1, ge=1)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class CostCentre(SQLModel, table=True):
    __tablename__ = "cost_centres"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    code: str = Field(max_length=50, index=True)
    name: str = Field(max_length=255)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

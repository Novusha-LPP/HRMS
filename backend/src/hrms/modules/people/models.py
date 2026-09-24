"""
People module — Person, Employment, Assignment, PersonnelAction.

Key design points (from the architecture):
- One Person can have many Employments (rejoin, multi-company).
- An Employment is sliced into Assignments: each slice is effective-dated
  and records the position, org unit, location, job, grade and managers at
  that point in time.  A GIST exclusion constraint (applied in the migration)
  prevents overlapping slices per employment.
- PersonnelAction is the only write path for employment changes; HR never
  PATCHes an assignment directly.
- sensitive identifiers (PAN, Aadhaar, UAN) are stored in a separate
  Identifier table with field-level encryption — not in Person.
"""

import enum
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class EmploymentState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    NOTICE = "NOTICE"
    ON_HOLD = "ON_HOLD"
    SEPARATED = "SEPARATED"


class PersonnelActionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    SCHEDULED = "SCHEDULED"


class PersonnelActionType(str, enum.Enum):
    HIRE = "HIRE"
    TRANSFER = "TRANSFER"
    PROMOTION = "PROMOTION"
    DEMOTION = "DEMOTION"
    CONFIRM = "CONFIRM"
    EXTEND_PROBATION = "EXTEND_PROBATION"
    PLACE_ON_NOTICE = "PLACE_ON_NOTICE"
    REHIRE = "REHIRE"
    SEPARATION = "SEPARATION"
    CHANGE_MANAGER = "CHANGE_MANAGER"
    CHANGE_GRADE = "CHANGE_GRADE"
    CHANGE_COST_CENTRE = "CHANGE_COST_CENTRE"


class Person(SQLModel, table=True):
    """
    The person record — created once; survives across employments and rehires.
    Contains only non-sensitive personal information.
    Sensitive identifiers (PAN, Aadhaar, UAN, bank account) are in PersonIdentifier.
    """
    __tablename__ = "persons"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    legal_first_name: str = Field(max_length=100)
    legal_last_name: str = Field(max_length=100)
    preferred_name: Optional[str] = Field(default=None, max_length=100)
    date_of_birth: Optional[date] = Field(default=None)
    gender: Optional[str] = Field(default=None, max_length=20)
    nationality: Optional[str] = Field(default=None, max_length=2)
    # custom_fields is a JSON dict validated against the tenant's field registry
    custom_fields: Optional[dict] = Field(default=None, sa_column=Column("custom_fields", JSONB))
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


class Employment(SQLModel, table=True):
    """
    One employment per legal entity per period.
    A person can have multiple employments (multi-company, rehire after gap).
    """
    __tablename__ = "employments"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    person_id: UUID = Field(index=True)
    legal_entity_id: UUID = Field()
    employee_number: str = Field(max_length=50, index=True)
    hire_date: date = Field()
    separation_date: Optional[date] = Field(default=None)
    employment_state: str = Field(default=EmploymentState.PROBATION, max_length=50)
    # Service stage (e.g. INTERN, CONTRACT, PERMANENT)
    service_stage: Optional[str] = Field(default=None, max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)


class Assignment(SQLModel, table=True):
    """
    Effective-dated slice of an employment.
    Each change (transfer, promotion, etc.) creates a new Assignment row and
    closes the previous one (sets effective_to).

    A GIST exclusion constraint on (tenant_id, employment_id, daterange) prevents gaps
    and overlaps — applied in the Alembic migration.
    """
    __tablename__ = "assignments"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    effective_from: date = Field()
    effective_to: Optional[date] = Field(default=None)
    org_unit_id: UUID = Field()
    location_id: UUID = Field()
    job_id: UUID = Field()
    grade_id: Optional[UUID] = Field(default=None)
    position_id: Optional[UUID] = Field(default=None)
    cost_centre_id: Optional[UUID] = Field(default=None)
    # FTE and worker type
    fte: float = Field(default=1.0)
    worker_type: str = Field(default="PERMANENT", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)


class AssignmentManager(SQLModel, table=True):
    """
    Reporting lines for an assignment.  A single assignment can have multiple
    managers of different types (LINE, FUNCTIONAL, DOTTED).
    """
    __tablename__ = "assignment_managers"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    assignment_id: UUID = Field(index=True)
    manager_employment_id: UUID = Field()
    manager_type: str = Field(default="LINE", max_length=50)
    effective_from: date = Field()
    effective_to: Optional[date] = Field(default=None)


class PersonnelAction(SQLModel, table=True):
    """
    The only write path for employment changes.
    POST /v1/personnel-actions → creates a PA → workflow approval → applied.

    `changes` is a JSON patch describing the delta: new values for whichever
    fields the action type modifies.
    """
    __tablename__ = "personnel_actions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    type: str = Field(max_length=50)
    reason_code: Optional[str] = Field(default=None, max_length=100)
    effective_date: date = Field()
    # JSON: the fields being changed and their new values
    changes: Optional[dict] = Field(default=None, sa_column=Column("changes", JSONB))
    status: str = Field(default=PersonnelActionStatus.DRAFT, max_length=50)
    # Idempotency key from the API caller
    idempotency_key: Optional[str] = Field(default=None, max_length=100, index=True)
    submitted_at: Optional[datetime] = Field(default=None)
    applied_at: Optional[datetime] = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)

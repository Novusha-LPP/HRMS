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
- sensitive identifiers (PAN, Aadhaar, UAN, bank account, …) are not in Person: they live
  in the KYC record (modules/kyc/models.py), encrypted at rest (core/field_crypto.py).
"""

import enum
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

ManagerType = Literal["LINE"]  # stored values; see hrms.db.conventions.DOMAINS


class EmploymentState(enum.StrEnum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    NOTICE = "NOTICE"
    ON_HOLD = "ON_HOLD"
    SEPARATED = "SEPARATED"


class PersonnelActionStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    SCHEDULED = "SCHEDULED"
    # A scheduled action that could no longer be applied when its date arrived
    # (e.g. a transfer scheduled after a separation). It is parked here with a
    # reason instead of failing requests; HR can cancel it or schedule a fix.
    FAILED = "FAILED"


class PersonnelActionType(enum.StrEnum):
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
    # A new designation (job title) that isn't a promotion (§7 "Designation change").
    CHANGE_JOB = "CHANGE_JOB"


class RejoinMode(enum.StrEnum):
    """What a rejoin does with the person's earlier service and leave."""

    CONTINUE = "CONTINUE"
    FRESH = "FRESH"


class RejoinPolicy(SQLModel, table=True):
    """How a company (or every company, when none is named) treats someone who rejoins."""

    __tablename__ = "rejoin_policies"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    legal_entity_id: UUID | None = Field(default=None)
    default_mode: str = Field(max_length=10)
    force_fresh_after_days: int | None = Field(default=None, ge=0)
    effective_from: date
    archived_at: datetime | None = Field(default=None)
    created_by: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)


class Person(SQLModel, table=True):
    """
    The person record — created once; survives across employments and rehires.
    Contains only non-sensitive personal information.
    Sensitive identifiers (PAN, Aadhaar, UAN, bank account) are in the encrypted KYC record.
    """

    __tablename__ = "persons"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    legal_first_name: str = Field(max_length=100)
    legal_last_name: str = Field(max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = Field(default=None)
    gender: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=2)
    # custom_fields is a JSON dict validated against the tenant's field registry
    custom_fields: dict | None = Field(default=None, sa_column=Column("custom_fields", JSONB))
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


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
    separation_date: date | None = Field(default=None)
    employment_state: str = Field(default=EmploymentState.PROBATION, max_length=50)
    # Service stage (e.g. INTERN, CONTRACT, PERMANENT)
    service_stage: str | None = Field(default=None, max_length=50)
    # Service is counted from here (leave eligibility, gratuity). Equal to hire_date until a
    # "start fresh" rejoin moves it; NULL only on rows written before the column existed.
    continuity_start_date: date | None = Field(default=None)
    current_spell_no: int = Field(default=1)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)


class EmploymentSpell(SQLModel, table=True):
    """One stint of an employment. A rejoin reuses the employment and opens the next stint."""

    __tablename__ = "employment_spells"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    spell_no: int = Field()
    joined_on: date = Field()
    left_on: date | None = Field(default=None)
    exit_reason: str | None = Field(default=None, max_length=100)
    gratuity_paid: bool | None = Field(default=None)
    leave_settled: bool = Field(default=False)
    created_by: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)


class RejoinRecord(SQLModel, table=True):
    """The decision taken when a separated employee rejoined."""

    __tablename__ = "rejoin_records"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    personnel_action_id: UUID | None = Field(default=None)
    previous_spell_id: UUID | None = Field(default=None)
    new_spell_id: UUID | None = Field(default=None)
    mode: str = Field(max_length=10)
    break_start: date | None = Field(default=None)
    break_end: date | None = Field(default=None)
    break_condoned: bool = Field(default=False)
    reason: str | None = Field(default=None)
    approved_by: UUID | None = Field(default=None)
    restored_leave: dict | None = Field(default=None, sa_column=Column("restored_leave", JSONB))
    created_by: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), nullable=False)


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
    effective_to: date | None = Field(default=None)
    org_unit_id: UUID = Field()
    location_id: UUID = Field()
    job_id: UUID = Field()
    grade_id: UUID | None = Field(default=None)
    position_id: UUID | None = Field(default=None)
    cost_centre_id: UUID | None = Field(default=None)
    # FTE and worker type
    fte: float = Field(default=1.0)
    worker_type: str = Field(default="PERMANENT", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
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
    effective_to: date | None = Field(default=None)


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
    reason_code: str | None = Field(default=None, max_length=100)
    effective_date: date = Field()
    # JSON: the fields being changed and their new values
    changes: dict | None = Field(default=None, sa_column=Column("changes", JSONB))
    status: str = Field(default=PersonnelActionStatus.DRAFT, max_length=50)
    # Idempotency key from the API caller
    idempotency_key: str | None = Field(default=None, max_length=100, index=True)
    submitted_at: datetime | None = Field(default=None)
    applied_at: datetime | None = Field(default=None)
    failure_reason: str | None = Field(default=None, max_length=500)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    recorded_by: UUID | None = Field(default=None)
    version: int = Field(default=0)

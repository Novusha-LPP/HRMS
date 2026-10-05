"""
Recruitment: job openings (requisitions) raised by department heads, team leads and
PMs, approved through the configurable approval flows, then worked by HR through a
tenant-defined candidate pipeline until a candidate is hired into an employment.

The schema is created by migration 0043; foreign keys that include tenant_id are
declared in hrms/model_registry.py.
"""

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class OpeningStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    FILLED = "FILLED"
    CLOSED = "CLOSED"


class StageCategory(enum.StrEnum):
    """What reaching a stage means, whatever the tenant calls it."""

    ACTIVE = "ACTIVE"  # still in the process
    HIRED = "HIRED"  # counts towards the opening's positions; can become an employee
    REJECTED = "REJECTED"  # turned down by the company
    WITHDRAWN = "WITHDRAWN"  # the candidate dropped out


class RecruitmentStage(SQLModel, table=True):
    """One column of the tenant's candidate pipeline, in `sequence` order."""

    __tablename__ = "recruitment_stages"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=60)
    category: str = Field(default=StageCategory.ACTIVE, max_length=20)
    color: str = Field(default="neutral", max_length=20)
    sequence: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    version: int = Field(default=1)


class JobOpening(SQLModel, table=True):
    __tablename__ = "job_openings"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    code: str = Field(max_length=20)
    title: str = Field(max_length=150)
    legal_entity_id: UUID = Field()
    org_unit_id: UUID = Field()
    job_id: UUID | None = Field(default=None)
    location_id: UUID | None = Field(default=None)
    hiring_manager_employment_id: UUID | None = Field(default=None)
    requested_by: UUID = Field()
    requester_employment_id: UUID | None = Field(default=None)
    employment_type: str = Field(max_length=20)
    work_mode: str = Field(max_length=20)
    positions: int = Field(default=1)
    priority: str = Field(max_length=20)
    reason: str = Field(max_length=20)
    replacement_for: str | None = Field(default=None, max_length=150)
    min_experience_years: Decimal | None = Field(default=None, max_digits=4, decimal_places=1)
    max_experience_years: Decimal | None = Field(default=None, max_digits=4, decimal_places=1)
    salary_min: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    salary_max: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", max_length=3)
    target_start_date: date | None = Field(default=None)
    description: str = Field()
    responsibilities: str | None = Field(default=None)
    requirements: str | None = Field(default=None)
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    status: str = Field(default=OpeningStatus.DRAFT, max_length=20)
    approval_mode: str | None = Field(default=None, max_length=10)
    submitted_at: datetime | None = Field(default=None)
    approved_at: datetime | None = Field(default=None)
    approved_by: UUID | None = Field(default=None)
    decision_comment: str | None = Field(default=None, max_length=1000)
    closed_at: datetime | None = Field(default=None)
    close_reason: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    version: int = Field(default=1)


class Candidate(SQLModel, table=True):
    """A person in the talent pool. One candidate can apply to several openings."""

    __tablename__ = "candidates"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=120)
    current_company: str | None = Field(default=None, max_length=150)
    current_title: str | None = Field(default=None, max_length=150)
    total_experience_years: Decimal | None = Field(default=None, max_digits=4, decimal_places=1)
    current_ctc: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    expected_ctc: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    notice_period_days: int | None = Field(default=None)
    source: str = Field(max_length=30)
    source_detail: str | None = Field(default=None, max_length=150)
    # [{"type": "LINKEDIN" | "GITHUB" | "PORTFOLIO" | "WEBSITE" | "OTHER", "label", "url"}]
    links: list[dict] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    summary: str | None = Field(default=None)
    resume_ref: str | None = Field(default=None, max_length=500)
    resume_file_name: str | None = Field(default=None, max_length=150)
    resume_mime_type: str | None = Field(default=None, max_length=100)
    resume_size: int | None = Field(default=None)
    resume_uploaded_at: datetime | None = Field(default=None)
    created_by: UUID = Field()
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    version: int = Field(default=1)


class JobApplication(SQLModel, table=True):
    """A candidate in one opening's pipeline."""

    __tablename__ = "job_applications"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    opening_id: UUID = Field()
    candidate_id: UUID = Field()
    stage_id: UUID = Field()
    rating: int | None = Field(default=None)
    owner_user_id: UUID | None = Field(default=None)
    hired_employment_id: UUID | None = Field(default=None)
    outcome_reason: str | None = Field(default=None, max_length=500)
    applied_at: datetime = Field(default_factory=_now)
    stage_changed_at: datetime = Field(default_factory=_now)
    created_by: UUID = Field()
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    version: int = Field(default=1)


class RecruitmentEvent(SQLModel, table=True):
    """Append-only history of an opening and its applications (also holds notes)."""

    __tablename__ = "recruitment_events"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    opening_id: UUID = Field()
    application_id: UUID | None = Field(default=None)
    actor_user_id: UUID | None = Field(default=None)
    action: str = Field(max_length=30)
    details: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=_now)

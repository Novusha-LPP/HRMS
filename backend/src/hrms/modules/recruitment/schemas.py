from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

EmploymentType = Literal["FULL_TIME", "PART_TIME", "CONTRACT", "INTERN", "CONSULTANT"]
WorkMode = Literal["ONSITE", "HYBRID", "REMOTE"]
Priority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
Reason = Literal["NEW_ROLE", "REPLACEMENT", "EXPANSION"]
StageCategory = Literal["ACTIVE", "HIRED", "REJECTED", "WITHDRAWN"]
StageColor = Literal["neutral", "brand", "info", "plum", "warning", "success", "danger"]
LinkType = Literal["LINKEDIN", "GITHUB", "PORTFOLIO", "WEBSITE", "OTHER"]
CandidateSource = Literal[
    "REFERRAL", "LINKEDIN", "JOB_PORTAL", "CAREERS_SITE", "AGENCY", "CAMPUS", "WALK_IN", "OTHER"
]


def _clean_skills(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for raw in values:
        skill = " ".join(raw.split())[:60]
        if skill and skill.lower() not in seen:
            seen[skill.lower()] = skill
    return list(seen.values())


def _blank_to_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# ─── Access & lookups ───────────────────────────────────────────────────────


class LookupItem(BaseModel):
    id: str
    name: str
    legal_entity_id: str | None = None
    detail: str | None = None


class RecruitmentAccess(BaseModel):
    can_request: bool
    can_manage: bool
    can_approve: bool
    departments: list[LookupItem]
    jobs: list[LookupItem]
    locations: list[LookupItem]
    hiring_managers: list[LookupItem]


# ─── Stages ─────────────────────────────────────────────────────────────────


class StageResponse(BaseModel):
    id: str
    name: str
    category: StageCategory
    color: str
    sequence: int
    is_active: bool
    version: int


class StageInput(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=60)
    category: StageCategory = "ACTIVE"
    color: StageColor = "neutral"
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Stage name is required")
        return v


class StagesUpdate(BaseModel):
    """The whole pipeline in display order. Stages left out are deactivated."""

    stages: list[StageInput] = Field(min_length=2, max_length=30)

    @model_validator(mode="after")
    def _check(self):
        names = [s.name.lower() for s in self.stages]
        if len(set(names)) != len(names):
            raise ValueError("Stage names must be unique")
        active = [s for s in self.stages if s.is_active]
        if not any(s.category == "ACTIVE" for s in active):
            raise ValueError("Keep at least one active in-progress stage")
        if not any(s.category == "HIRED" for s in active):
            raise ValueError("Keep at least one active hired stage")
        if not any(s.category in ("REJECTED", "WITHDRAWN") for s in active):
            raise ValueError("Keep at least one active rejected or withdrawn stage")
        return self


# ─── Openings ───────────────────────────────────────────────────────────────


class OpeningInput(BaseModel):
    title: str = Field(min_length=2, max_length=150)
    org_unit_id: str
    job_id: str | None = None
    location_id: str | None = None
    hiring_manager_employment_id: str | None = None
    employment_type: EmploymentType = "FULL_TIME"
    work_mode: WorkMode = "ONSITE"
    positions: int = Field(default=1, ge=1, le=500)
    priority: Priority = "MEDIUM"
    reason: Reason = "NEW_ROLE"
    replacement_for: str | None = Field(default=None, max_length=150)
    min_experience_years: Decimal | None = Field(default=None, ge=0, le=60)
    max_experience_years: Decimal | None = Field(default=None, ge=0, le=60)
    salary_min: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999999"))
    salary_max: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999999"))
    currency: str = Field(default="INR", min_length=3, max_length=3)
    target_start_date: date | None = None
    description: str = Field(min_length=10, max_length=20000)
    responsibilities: str | None = Field(default=None, max_length=20000)
    requirements: str | None = Field(default=None, max_length=20000)
    skills: list[str] = Field(default_factory=list, max_length=50)

    _blank = field_validator(
        "job_id",
        "location_id",
        "hiring_manager_employment_id",
        "replacement_for",
        "responsibilities",
        "requirements",
        mode="before",
    )(_blank_to_none)

    @field_validator("title", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        if not v.isalpha():
            raise ValueError("Currency must be a 3-letter code")
        return v.upper()

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        return _clean_skills(v)

    @model_validator(mode="after")
    def _ranges(self):
        if (
            self.min_experience_years is not None
            and self.max_experience_years is not None
            and self.max_experience_years < self.min_experience_years
        ):
            raise ValueError("Maximum experience must be at least the minimum")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("Maximum salary must be at least the minimum")
        if self.reason == "REPLACEMENT" and not self.replacement_for:
            raise ValueError("Say who this opening replaces")
        return self


class OpeningDecision(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    comments: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _reason(self):
        if self.action == "REJECT" and not (self.comments or "").strip():
            raise ValueError("Give a reason for rejecting the opening")
        return self


class OpeningStatusChange(BaseModel):
    status: Literal["OPEN", "ON_HOLD", "CLOSED"]
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _reason(self):
        if self.status in ("ON_HOLD", "CLOSED") and not (self.reason or "").strip():
            raise ValueError("Give a reason")
        return self


class StageCount(BaseModel):
    stage_id: str
    count: int


class OpeningSummary(BaseModel):
    id: str
    code: str
    title: str
    status: str
    priority: str
    employment_type: str
    work_mode: str
    positions: int
    hired: int
    candidates: int
    in_progress: int
    legal_entity_id: str
    legal_entity_name: str | None
    org_unit_id: str
    org_unit_name: str | None
    job_title: str | None
    location_name: str | None
    hiring_manager_employment_id: str | None
    hiring_manager_name: str | None
    requested_by_name: str | None
    target_start_date: date | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    stage_counts: list[StageCount]


class OpeningDetail(OpeningSummary):
    job_id: str | None
    location_id: str | None
    reason: str
    replacement_for: str | None
    min_experience_years: Decimal | None
    max_experience_years: Decimal | None
    # Compensation is visible to HR and the requester / hiring manager, not to others.
    salary_min: Decimal | None
    salary_max: Decimal | None
    currency: str
    description: str
    responsibilities: str | None
    requirements: str | None
    skills: list[str]
    approval_mode: str | None
    approval_instance_id: str | None
    approved_at: datetime | None
    approved_by_name: str | None
    decision_comment: str | None
    closed_at: datetime | None
    close_reason: str | None
    version: int
    can_edit: bool
    can_submit: bool
    can_withdraw: bool
    can_decide: bool
    can_manage: bool


# ─── Candidates & applications ──────────────────────────────────────────────


class CandidateLink(BaseModel):
    type: LinkType = "OTHER"
    label: str | None = Field(default=None, max_length=60)
    url: str = Field(max_length=500)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if v and "://" not in v:
            v = "https://" + v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or " " in v:
            raise ValueError("Enter a valid http(s) link")
        return v

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v):
        return _blank_to_none(v)


class CandidateInput(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=120)
    current_company: str | None = Field(default=None, max_length=150)
    current_title: str | None = Field(default=None, max_length=150)
    total_experience_years: Decimal | None = Field(default=None, ge=0, le=60)
    current_ctc: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999999"))
    expected_ctc: Decimal | None = Field(default=None, ge=0, le=Decimal("999999999999"))
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    source: CandidateSource = "OTHER"
    source_detail: str | None = Field(default=None, max_length=150)
    links: list[CandidateLink] = Field(default_factory=list, max_length=15)
    skills: list[str] = Field(default_factory=list, max_length=50)
    summary: str | None = Field(default=None, max_length=10000)

    _blank = field_validator(
        "email",
        "phone",
        "location",
        "current_company",
        "current_title",
        "source_detail",
        "summary",
        mode="before",
    )(_blank_to_none)

    @field_validator("first_name", "last_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.lower()
        local, _, domain = v.partition("@")
        if not local or "." not in domain or " " in v:
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        return _clean_skills(v)

    @field_validator("links")
    @classmethod
    def _links(cls, v: list[CandidateLink]) -> list[CandidateLink]:
        seen, out = set(), []
        for link in v:
            if link.url.lower() not in seen:
                seen.add(link.url.lower())
                out.append(link)
        return out


class CandidateResume(BaseModel):
    file_name: str
    mime_type: str
    size: int
    uploaded_at: datetime


class CandidateResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    full_name: str
    email: str | None
    phone: str | None
    location: str | None
    current_company: str | None
    current_title: str | None
    total_experience_years: Decimal | None
    # None for viewers who aren't recruiters (hiring managers don't see pay history).
    current_ctc: Decimal | None
    expected_ctc: Decimal | None
    notice_period_days: int | None
    source: str
    source_detail: str | None
    links: list[CandidateLink]
    skills: list[str]
    summary: str | None
    resume: CandidateResume | None
    created_at: datetime
    updated_at: datetime
    version: int


class ApplicationCreate(BaseModel):
    """Add a candidate to an opening: an existing one (candidate_id) or a new one."""

    candidate_id: str | None = None
    candidate: CandidateInput | None = None
    stage_id: str | None = None
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _one(self):
        if bool(self.candidate_id) == bool(self.candidate):
            raise ValueError("Provide either an existing candidate or new candidate details")
        return self


class ApplicationMove(BaseModel):
    stage_id: str
    reason: str | None = Field(default=None, max_length=500)
    expected_version: int | None = None


class ApplicationUpdate(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    clear_rating: bool = False


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Write a note")
        return v


class ApplicationHire(BaseModel):
    employment_id: str


class EventResponse(BaseModel):
    id: str
    action: str
    actor_name: str | None
    application_id: str | None
    candidate_name: str | None
    details: dict
    created_at: datetime


class ApplicationSummary(BaseModel):
    id: str
    opening_id: str
    opening_code: str
    opening_title: str
    opening_status: str
    candidate: CandidateResponse
    stage_id: str
    stage_name: str
    stage_category: str
    rating: int | None
    hired_employment_id: str | None
    outcome_reason: str | None
    applied_at: datetime
    stage_changed_at: datetime
    notes_count: int
    version: int


class ApplicationDetail(ApplicationSummary):
    events: list[EventResponse]
    other_applications: list[dict]
    can_manage: bool
    can_hire: bool
    hire_defaults: dict | None


class CandidateListItem(BaseModel):
    candidate: CandidateResponse
    applications: list[dict]

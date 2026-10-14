"""Request and response bodies for /v1/integrations/* and the admin screens' API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from hrms.modules.kernel.auth.schemas import check_password_bytes

# Stored values (hrms.db.conventions.DOMAINS checks the database CHECKs against these).
AppKind = Literal["TWO_WAY", "RECEIVE_ONLY", "READ_ONLY"]
AppStatus = Literal["ACTIVE", "PAUSED", "DISCONNECTED"]
MappingKind = Literal["LEGAL_ENTITY", "DEPARTMENT", "LOCATION", "DESIGNATION", "ROLE"]
ProfileStatus = Literal["DRAFT", "PUBLISHED", "SUPERSEDED", "DISCARDED"]
DuplicateStatus = Literal["OPEN", "SAME_PERSON", "DIFFERENT_PERSON"]


class _Body(BaseModel):
    # Unknown fields are refused rather than silently ignored, so a misspelt field name shows up
    # in testing instead of as data that never arrives.
    model_config = ConfigDict(extra="forbid")


# ─── Employee sync ───────────────────────────────────────────────────────────


class EmployeeUpsert(_Body):
    source_updated_at: datetime | None = Field(
        default=None,
        description="When the record changed in your system. Older updates than the last one "
        "applied are ignored (outcome STALE_IGNORED).",
    )
    employment_id: str | None = Field(
        default=None, description="Link to an employee already in HRMS (emp_…)."
    )
    employee_code: str | None = Field(default=None, max_length=50)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    preferred_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, max_length=20)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    company: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    designation: str | None = Field(default=None, max_length=200)
    manager_external_id: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, max_length=40)
    hire_date: date | None = None
    effective_date: date | None = Field(
        default=None, description="When a job change takes effect. Default: today."
    )
    change_reason: Literal["TRANSFER", "PROMOTION", "CORRECTION"] | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
    password_hash: str | None = Field(default=None, max_length=100)

    _password_bytes = field_validator("password")(
        lambda v: check_password_bytes(v) if v is not None else v
    )


class ExitRequest(_Body):
    last_working_day: date
    reason_code: str | None = Field(default=None, max_length=50)
    source_updated_at: datetime | None = None


class RehireRequest(_Body):
    hire_date: date
    department: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    designation: str | None = Field(default=None, max_length=200)
    manager_external_id: str | None = Field(default=None, max_length=100)
    source_updated_at: datetime | None = None


class BulkRecord(EmployeeUpsert):
    external_id: str = Field(min_length=1, max_length=100)


class BulkRequest(_Body):
    records: list[BulkRecord] = Field(min_length=1, max_length=200)


class LinkRecord(_Body):
    external_id: str = Field(min_length=1, max_length=100)
    employee_code: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None


class LinkRequest(_Body):
    records: list[LinkRecord] = Field(min_length=1, max_length=2000)
    dry_run: bool = True


class ReconcileRequest(_Body):
    active_external_ids: list[str] = Field(max_length=200_000)


class SessionRequest(_Body):
    external_id: str = Field(min_length=1, max_length=100)


class SyncResult(BaseModel):
    outcome: str
    external_id: str
    employment_id: str | None = None
    user_id: str | None = None
    employee_code: str | None = None
    changes: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    dry_run: bool = False
    request_id: str | None = None


class BulkItem(BaseModel):
    external_id: str
    status: int
    result: SyncResult | None = None
    error: dict[str, Any] | None = None


class BulkResponse(BaseModel):
    results: list[BulkItem]
    created: int
    updated: int
    unchanged: int
    failed: int


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    employment_id: str
    roles: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    scope: str


class FeedResponse(BaseModel):
    events: list[dict[str, Any]]
    next_cursor: str
    has_more: bool


# ─── Admin screens ───────────────────────────────────────────────────────────


class AppCreate(_Body):
    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{1,39}$")
    name: str = Field(min_length=1, max_length=120)
    kind: AppKind


class AppUpdate(_Body):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: AppStatus | None = None


class AppResponse(BaseModel):
    id: str
    code: str
    name: str
    kind: str
    status: str
    created_at: datetime
    linked_employees: int = 0
    active_keys: int = 0
    last_request_at: datetime | None = None
    feed_position: str | None = None
    feed_read_at: datetime | None = None
    feed_lag: int = 0


class KeyCreate(_Body):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1)
    allowed_ips: list[str] | None = None
    legal_entity_ids: list[str] | None = None
    expires_in_days: int | None = Field(default=365, ge=1, le=730)
    rate_limit_per_minute: int = Field(default=600, ge=10, le=10_000)


class KeyRevoke(_Body):
    reason: str = Field(min_length=3, max_length=200)


class KeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    client_id: str
    environment: str
    scopes: list[str]
    allowed_ips: list[str] | None
    legal_entity_ids: list[str] | None
    status: str
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None
    last_used_ip: str | None
    calls_last_hour: int = 0
    rate_limit_per_minute: int
    revoked_at: datetime | None = None
    revoke_reason: str | None = None


class KeyCreated(KeyResponse):
    key: str = Field(description="Shown once. Store it in your server's secret store.")


class ProfileCreate(_Body):
    legal_entity_id: str | None = None
    preset: Literal["ERP_MASTER", "HRMS_MASTER", "SHARED"] | None = None
    copy_from: Literal["CURRENT"] | None = "CURRENT"
    settings: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=500)


class ProfileUpdate(_Body):
    settings: dict[str, Any]
    note: str | None = Field(default=None, max_length=500)


class ProfilePublish(_Body):
    effective_from: date


class ProfileResponse(BaseModel):
    id: str
    app_id: str
    legal_entity_id: str | None
    version: int
    status: str
    effective_from: date | None
    settings: dict[str, Any]
    note: str | None
    created_at: datetime
    published_at: datetime | None


class MappingCreate(_Body):
    kind: MappingKind
    external_value: str = Field(min_length=1, max_length=200)
    target_id: str | None = None
    target_value: Literal["EMPLOYEE", "MANAGER"] | None = None


class MappingResponse(BaseModel):
    id: str
    kind: str
    external_value: str
    target_id: str | None
    target_value: str | None
    target_name: str | None
    created_at: datetime


class DuplicateResolve(_Body):
    decision: Literal["SAME_PERSON", "DIFFERENT_PERSON"]


class HeldExitDecision(_Body):
    decision: Literal["RELEASE", "REJECT"]

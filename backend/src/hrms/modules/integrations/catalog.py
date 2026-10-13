"""
What an integration can be configured to do: the field catalogue, the settings schema, the
presets, and how a company override is laid over the tenant default.

Everything a tenant can change lives in IntegrationSettings. Rules that must never be a
setting (plan §6.4) are enforced in code elsewhere and are deliberately absent here.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ─── The field catalogue ─────────────────────────────────────────────────────
# Every field that can be synced, owned or sent. A new field is added here once; ownership,
# enforcement, the field-control endpoint and outbound filtering all read this.

DataClass = Literal["BASIC", "CONTACT", "PERSONAL", "ATTENDANCE_LEAVE"]

FIELDS: dict[str, dict[str, str]] = {
    "first_name": {"label": "First name", "data_class": "BASIC"},
    "last_name": {"label": "Last name", "data_class": "BASIC"},
    "preferred_name": {"label": "Preferred name", "data_class": "BASIC"},
    "employee_code": {"label": "Employee code", "data_class": "BASIC"},
    "company": {"label": "Company", "data_class": "BASIC"},
    "department": {"label": "Department", "data_class": "BASIC"},
    "location": {"label": "Location", "data_class": "BASIC"},
    "designation": {"label": "Designation", "data_class": "BASIC"},
    "manager": {"label": "Manager", "data_class": "BASIC"},
    "role": {"label": "Role (employee or manager)", "data_class": "BASIC"},
    "hire_date": {"label": "Hire date", "data_class": "BASIC"},
    "last_working_day": {"label": "Last working day", "data_class": "BASIC"},
    "employment_state": {"label": "Employment status", "data_class": "BASIC"},
    "email": {"label": "Email", "data_class": "CONTACT"},
    "mobile": {"label": "Mobile", "data_class": "CONTACT"},
    "date_of_birth": {"label": "Date of birth", "data_class": "PERSONAL"},
    "gender": {"label": "Gender", "data_class": "PERSONAL"},
}

# Fields an app may own. employment_state is derived from exits and rehires, not edited.
OWNABLE_FIELDS = tuple(f for f in FIELDS if f != "employment_state")

Owner = Literal["APP", "HRMS", "SHARED", "NOT_SYNCED"]
Lifecycle = Literal["APP", "HRMS", "BOTH"]

EVENT_TYPES: tuple[str, ...] = (
    "employee.hired",
    "employee.updated",
    "employee.manager_changed",
    "employee.separated",
    "employee.rehired",
    "employee.hire_cancelled",
)


# ─── Settings ────────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LifecycleSettings(_Strict):
    hire: Lifecycle = "BOTH"
    job_change: Lifecycle = "BOTH"
    exit: Lifecycle = "BOTH"
    rehire: Lifecycle = "BOTH"


class LoginSettings(_Strict):
    # APP_THEN_DEFAULT: the app's password if it sends one, else the default pattern.
    # NONE: no direct HRMS sign-in; the employee uses HRMS only through the app.
    password_source: Literal["APP_THEN_DEFAULT", "DEFAULT", "NONE"] = "APP_THEN_DEFAULT"
    default_pattern: str = Field(default="{FirstName}@1234", min_length=8, max_length=60)
    force_change: bool = True

    @field_validator("default_pattern")
    @classmethod
    def _pattern_has_a_name(cls, value: str) -> str:
        if not any(token in value for token in ("{FirstName}", "{LastName}", "{EmployeeCode}")):
            raise ValueError(
                "The default password pattern must include {FirstName}, {LastName} or "
                "{EmployeeCode}, or every employee would get the same password"
            )
        return value


class SelfServiceSettings(_Strict):
    punch: bool = True
    attendance: bool = True
    corrections: bool = True
    leave: bool = True
    profile_edit: bool = True
    approvals: bool = True
    session_minutes: int = Field(default=60, ge=5, le=480)


class SafetySettings(_Strict):
    max_exits_per_day: int = Field(default=20, ge=1, le=100_000)
    max_exit_percent: float = Field(default=5.0, gt=0, le=100)
    over_limit: Literal["HOLD", "REJECT"] = "HOLD"


class OutboundTiming(_Strict):
    # When a new joiner becomes visible to this app.
    mode: Literal["ON_SAVE", "DAYS_BEFORE_JOIN", "ON_JOIN"] = "ON_SAVE"
    days: int = Field(default=3, ge=0, le=90)


class OutboundSettings(_Strict):
    events: list[str] = Field(default_factory=lambda: list(EVENT_TYPES))
    data_classes: list[DataClass] = Field(
        default_factory=lambda: list[DataClass](["BASIC", "CONTACT", "PERSONAL"])
    )
    # None = every field in the allowed data classes.
    fields: list[str] | None = None
    # Which people the app sees. None = every company the app's credentials cover.
    legal_entity_ids: list[str] | None = None
    org_unit_ids: list[str] | None = None
    timing: OutboundTiming = Field(default_factory=OutboundTiming)

    @field_validator("events")
    @classmethod
    def _known_events(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(EVENT_TYPES))
        if unknown:
            raise ValueError(f"Unknown events: {', '.join(unknown)}")
        return value

    @field_validator("fields")
    @classmethod
    def _known_fields(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            unknown = sorted(set(value) - set(FIELDS))
            if unknown:
                raise ValueError(f"Unknown fields: {', '.join(unknown)}")
        return value


class IntegrationSettings(_Strict):
    field_ownership: dict[str, Owner] = Field(default_factory=dict)
    inbound_unowned: Literal["IGNORE", "REJECT"] = "IGNORE"
    # Editing a field the app owns, in HRMS. WITH_APPROVAL sends the change (a personnel
    # action) through the employee's FIELD_OVERRIDE approval flow before it applies.
    hr_override: Literal["NOT_ALLOWED", "WITH_REASON", "WITH_APPROVAL"] = "WITH_REASON"
    lifecycle: LifecycleSettings = Field(default_factory=LifecycleSettings)
    unknown_values: Literal["REJECT", "CREATE"] = "REJECT"
    matching: Literal["CODE_NAME_DOB", "CODE_EMAIL", "NEVER"] = "CODE_NAME_DOB"
    logins: LoginSettings = Field(default_factory=LoginSettings)
    self_service: SelfServiceSettings = Field(default_factory=SelfServiceSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    outbound: OutboundSettings = Field(default_factory=OutboundSettings)
    default_location_id: str | None = None
    retention_days: int = Field(default=400, ge=90, le=1095)

    @field_validator("field_ownership")
    @classmethod
    def _ownable(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(OWNABLE_FIELDS))
        if unknown:
            raise ValueError(f"These fields can't be owned: {', '.join(unknown)}")
        return value

    def owner(self, field: str) -> str:
        return self.field_ownership.get(field, "HRMS")


# ─── Presets ─────────────────────────────────────────────────────────────────

_ERP_MASTER = {
    **{
        f: "APP"
        for f in (
            "first_name",
            "last_name",
            "preferred_name",
            "employee_code",
            "company",
            "department",
            "location",
            "designation",
            "manager",
            "role",
            "hire_date",
            "last_working_day",
            "date_of_birth",
            "gender",
        )
    },
    "email": "SHARED",
    "mobile": "SHARED",
}
PRESETS: dict[str, dict[str, Any]] = {
    "ERP_MASTER": {
        "label": "ERP is master for job data",
        "description": "The app owns names, code, company, department, location, designation, "
        "manager, dates, date of birth and gender. Email and mobile are shared. HRMS owns "
        "everything else.",
        "field_ownership": _ERP_MASTER,
    },
    "HRMS_MASTER": {
        "label": "HRMS is master",
        "description": "HRMS owns every field. The app only receives changes.",
        "field_ownership": {f: "HRMS" for f in OWNABLE_FIELDS},
    },
    "SHARED": {
        "label": "Shared",
        "description": "Both sides edit every field. The most recent change in the source wins.",
        "field_ownership": {f: "SHARED" for f in OWNABLE_FIELDS},
    },
}


def defaults_for(kind: str) -> dict[str, Any]:
    """The built-in settings an app starts with before anything is published."""
    base = IntegrationSettings().model_dump()
    if kind == "TWO_WAY":
        base["field_ownership"] = dict(PRESETS["ERP_MASTER"]["field_ownership"])
    else:
        # A receive-only or read-only app never writes, so it owns nothing.
        base["field_ownership"] = dict(PRESETS["HRMS_MASTER"]["field_ownership"])
        base["lifecycle"] = {"hire": "HRMS", "job_change": "HRMS", "exit": "HRMS", "rehire": "HRMS"}
    return base


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Lay a (partial) company override over a full settings dict. Lists replace; dicts merge."""
    out = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def overridden_paths(override: dict[str, Any], prefix: str = "") -> list[str]:
    """Dotted paths a company override sets, so the screen can mark them 'overridden'."""
    paths: list[str] = []
    for key, value in override.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and key != "field_ownership":
            paths.extend(overridden_paths(value, path + "."))
        elif key == "field_ownership" and isinstance(value, dict):
            paths.extend(f"field_ownership.{f}" for f in value)
        else:
            paths.append(path)
    return paths


def validate_full(settings: dict[str, Any]) -> IntegrationSettings:
    return IntegrationSettings.model_validate(settings)


def password_from_pattern(pattern: str, first_name: str, last_name: str, code: str) -> str:
    def clean(value: str) -> str:
        value = "".join(value.split())
        return value[:1].upper() + value[1:] if value else value

    return (
        pattern.replace("{FirstName}", clean(first_name))
        .replace("{LastName}", clean(last_name))
        .replace("{EmployeeCode}", code)
    )

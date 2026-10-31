from datetime import date, datetime, time

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from hrms.core.versioning import version_field
from hrms.modules.reminders.dates import MAX_OFFSET
from hrms.modules.reminders.models import (
    OutboxStatus,
    ReminderFrequency,
    ReminderTrigger,
)
from hrms.modules.reminders.templates import MAX_BODY

MAX_EXTRA = 50


class RuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Birthdays: HR heads-up"])
    trigger: ReminderTrigger
    legal_entity_id: str | None = Field(
        default=None, description="Only people of this company; empty means the whole group"
    )
    org_unit_id: str | None = Field(default=None, description="Only people in this department")
    frequency: ReminderFrequency
    days_before: int = Field(
        default=0,
        ge=0,
        le=60,
        description="How many days ahead it starts. Used by CONTINUOUS and ALTERNATE_DAYS",
    )
    custom_offsets: list[int] = Field(
        default_factory=list,
        description="CUSTOM only: days before the day to send, 0 being the day itself",
    )
    send_time: time = Field(description="Time of day in the company's timezone", examples=["09:00"])
    notify_employee: bool = False
    notify_manager: bool = False
    notify_everyone: bool = Field(
        default=False,
        description="Also mail every employee with an email address, about everyone else",
    )
    extra_emails: list[EmailStr] = Field(default_factory=list, max_length=MAX_EXTRA)
    digest: bool = Field(
        default=True, description="One mail listing everyone due, instead of one mail per person"
    )
    subject: str = Field(min_length=1, max_length=300)
    body_html: str = Field(min_length=1, max_length=MAX_BODY)
    employee_subject: str = Field(min_length=1, max_length=300)
    employee_body_html: str = Field(min_length=1, max_length=MAX_BODY)
    is_active: bool = True

    @field_validator("custom_offsets")
    @classmethod
    def _offsets(cls, value: list[int]) -> list[int]:
        if any(not 0 <= v <= MAX_OFFSET for v in value):
            raise ValueError(f"Each day must be between 0 and {MAX_OFFSET}")
        return sorted(set(value))

    @field_validator("extra_emails")
    @classmethod
    def _emails(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip().lower() for v in value))

    @model_validator(mode="after")
    def _consistent(self):
        if not (
            self.notify_employee or self.notify_manager or self.notify_everyone or self.extra_emails
        ):
            raise ValueError("Choose at least one person to tell")
        if self.frequency == ReminderFrequency.CUSTOM and not self.custom_offsets:
            raise ValueError("Enter at least one day for a custom schedule")
        if self.frequency in {ReminderFrequency.CONTINUOUS, ReminderFrequency.ALTERNATE_DAYS} and (
            self.days_before < 1
        ):
            raise ValueError("Say how many days before it starts")
        return self


class RuleCreate(RuleBase):
    pass


class RuleUpdate(BaseModel):
    """Any field of a rule; send only what changes."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    legal_entity_id: str | None = None
    org_unit_id: str | None = None
    frequency: ReminderFrequency | None = None
    days_before: int | None = Field(default=None, ge=0, le=60)
    custom_offsets: list[int] | None = None
    send_time: time | None = None
    notify_employee: bool | None = None
    notify_manager: bool | None = None
    notify_everyone: bool | None = None
    extra_emails: list[EmailStr] | None = Field(default=None, max_length=MAX_EXTRA)
    digest: bool | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body_html: str | None = Field(default=None, min_length=1, max_length=MAX_BODY)
    employee_subject: str | None = Field(default=None, min_length=1, max_length=300)
    employee_body_html: str | None = Field(default=None, min_length=1, max_length=MAX_BODY)
    is_active: bool | None = None
    version: int | None = version_field()


class RuleResponse(RuleBase):
    id: str
    version: int
    last_run_date: date | None
    created_at: datetime
    updated_at: datetime


class DraftPreview(BaseModel):
    trigger: ReminderTrigger
    audience: str = Field(pattern="^(EMPLOYEE|TEAM)$")
    subject: str = Field(max_length=300)
    body_html: str = Field(max_length=MAX_BODY)
    digest: bool = True
    legal_entity_id: str | None = None


class PreviewResponse(BaseModel):
    subject: str
    html: str
    text: str
    problems: list[str]


class UpcomingPerson(BaseModel):
    full_name: str
    department: str
    event_date: date
    days_left: int
    sends_on: list[date]


class DeliveryResponse(BaseModel):
    id: str
    rule_id: str
    send_date: date
    audience: str
    recipient_email: str
    status: OutboxStatus
    attempts: int
    sent_at: datetime | None
    last_error: str | None


class ChangeResponse(BaseModel):
    action: str
    changed_by: str
    changed_at: datetime
    changes: dict

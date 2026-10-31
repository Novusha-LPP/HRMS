"""
Date reminders (migration 0076): birthday and work-anniversary mail on a schedule.

- Triggers: BIRTHDAY and WORK_ANNIVERSARY repeat every year; NEW_JOINER (hire date) and EXIT
  (separation date) are one-off dates.
- ReminderRule: when it runs (frequency, days before, time of day in the tenant's timezone),
  who is told (the person, their manager, extra addresses) and the wording. `custom_offsets`
  is only read for frequency CUSTOM.
- ReminderOutbox: one queued mail. The people are a payload and the mail is worded when it is
  sent, so an edit to a rule's wording applies to mail that has not gone out yet.
"""

import enum
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import ARRAY, Column, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ReminderTrigger(enum.StrEnum):
    BIRTHDAY = "BIRTHDAY"
    WORK_ANNIVERSARY = "WORK_ANNIVERSARY"
    NEW_JOINER = "NEW_JOINER"
    EXIT = "EXIT"


class ReminderFrequency(enum.StrEnum):
    SAME_DAY = "SAME_DAY"
    ONE_DAY_BEFORE = "ONE_DAY_BEFORE"
    CONTINUOUS = "CONTINUOUS"
    ALTERNATE_DAYS = "ALTERNATE_DAYS"
    CUSTOM = "CUSTOM"


class Audience(enum.StrEnum):
    EMPLOYEE = "EMPLOYEE"
    TEAM = "TEAM"


class OutboxStatus(enum.StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class ReminderRule(SQLModel, table=True):
    __tablename__ = "reminder_rules"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=120)
    trigger: str = Field(max_length=20)
    legal_entity_id: UUID | None = Field(default=None)
    org_unit_id: UUID | None = Field(default=None)
    frequency: str = Field(max_length=20)
    days_before: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False))
    custom_offsets: list[int] = Field(
        default_factory=list, sa_column=Column(ARRAY(SmallInteger), nullable=False)
    )
    send_time: time = Field()
    notify_employee: bool = Field(default=False)
    notify_manager: bool = Field(default=False)
    notify_everyone: bool = Field(default=False)
    extra_emails: list[str] = Field(
        default_factory=list, sa_column=Column(ARRAY(String), nullable=False)
    )
    digest: bool = Field(default=True)
    subject: str = Field(max_length=300)
    body_html: str = Field()
    employee_subject: str = Field(max_length=300)
    employee_body_html: str = Field()
    is_active: bool = Field(default=True)
    last_run_date: date | None = Field(default=None)
    version: int = Field(default=0)
    created_by: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID | None = Field(default=None)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    archived_at: datetime | None = Field(default=None)


class ReminderOutbox(SQLModel, table=True):
    __tablename__ = "reminder_outbox"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    rule_id: UUID = Field()
    send_date: date = Field()
    audience: str = Field(max_length=10)
    recipient_email: str = Field(max_length=320)
    dedupe_key: str = Field(max_length=200)
    payload: dict = Field(sa_column=Column(JSONB, nullable=False))
    status: str = Field(default=OutboxStatus.PENDING, max_length=10)
    attempts: int = Field(default=0, sa_column=Column(SmallInteger, nullable=False))
    next_attempt_at: datetime | None = Field(default=None)
    sent_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

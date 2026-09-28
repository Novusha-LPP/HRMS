import enum
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class ReportModule(enum.StrEnum):
    ATTENDANCE = "ATTENDANCE"
    EMPLOYEE = "EMPLOYEE"
    ONBOARDING = "ONBOARDING"
    LEAVE = "LEAVE"
    HEADCOUNT = "HEADCOUNT"


class ReportDefinition(SQLModel, table=True):
    """
    Saved report definition — system defaults + user-created custom reports.

    `columns` and `filters` are JSON arrays stored as text.
    columns: [{"field": "work_date", "label": "Date", "visible": true}, ...]
    filters: [{"field": "work_date", "op": "gte", "value": "2026-09-01"}, ...]
    """

    __tablename__ = "report_definitions"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=500)
    module: str = Field(max_length=50)
    # JSON stored as text
    columns: str = Field(default="[]")
    filters: str = Field(default="[]")
    is_system: bool = Field(default=False)
    # HR / EMPLOYEE / ALL — who can see/run this report
    owner_type: str = Field(default="HR", max_length=50)
    created_by: UUID | None = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=0)
    archived_at: datetime | None = Field(default=None)

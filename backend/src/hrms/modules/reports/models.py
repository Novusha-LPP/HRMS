import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class ReportModule(str, enum.Enum):
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
    description: Optional[str] = Field(default=None, max_length=500)
    module: str = Field(max_length=50)
    # JSON stored as text
    columns: str = Field(default="[]")
    filters: str = Field(default="[]")
    is_system: bool = Field(default=False)
    # HR / EMPLOYEE / ALL — who can see/run this report
    owner_type: str = Field(default="HR", max_length=50)
    created_by: Optional[UUID] = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)
    archived_at: Optional[datetime] = Field(default=None)

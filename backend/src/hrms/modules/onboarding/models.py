import enum
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class OnboardingItemType(str, enum.Enum):
    DOCUMENT = "DOCUMENT"
    TASK = "TASK"
    POLICY_ACK = "POLICY_ACK"
    IT_SETUP = "IT_SETUP"
    FORM = "FORM"
    TRAINING = "TRAINING"


class AssigneeType(str, enum.Enum):
    HR = "HR"
    EMPLOYEE = "EMPLOYEE"
    IT = "IT"
    MANAGER = "MANAGER"


class ItemStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    OVERDUE = "OVERDUE"


class CaseStatus(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OnboardingTemplate(SQLModel, table=True):
    """Reusable checklist definition. One default per tenant + custom ones."""
    __tablename__ = "onboarding_templates"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    # HIRE = new hires, REHIRE = rejoining employees
    trigger: str = Field(default="HIRE", max_length=50)
    is_default: bool = Field(default=False)
    status: str = Field(default="ACTIVE", max_length=50)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)


class OnboardingTemplateItem(SQLModel, table=True):
    """An item in a template. Ordered by sequence."""
    __tablename__ = "onboarding_template_items"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    template_id: UUID = Field(index=True)
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    item_type: str = Field(default=OnboardingItemType.TASK, max_length=50)
    assignee_type: str = Field(default=AssigneeType.EMPLOYEE, max_length=50)
    due_days_from_hire: int = Field(default=7)
    required: bool = Field(default=True)
    sequence: int = Field(default=0)


class OnboardingCase(SQLModel, table=True):
    """One onboarding instance per employment (created on hire)."""
    __tablename__ = "onboarding_cases"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    template_id: UUID = Field()
    status: str = Field(default=CaseStatus.IN_PROGRESS, max_length=50)
    hire_date: date = Field()
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)


class OnboardingItem(SQLModel, table=True):
    """Instantiated checklist item for a specific onboarding case."""
    __tablename__ = "onboarding_items"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    case_id: UUID = Field(index=True)
    template_item_id: Optional[UUID] = Field(default=None)
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    item_type: str = Field(max_length=50)
    assignee_type: str = Field(max_length=50)
    due_date: Optional[date] = Field(default=None)
    required: bool = Field(default=True)
    sequence: int = Field(default=0)
    status: str = Field(default=ItemStatus.PENDING, max_length=50)
    completed_at: Optional[datetime] = Field(default=None)
    completed_by: Optional[UUID] = Field(default=None)
    # For DOCUMENT type: S3 key or link
    document_key: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=1000)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = Field(default=0)

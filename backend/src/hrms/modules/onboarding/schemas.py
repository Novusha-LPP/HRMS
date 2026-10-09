from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from hrms.modules.onboarding.models import AssigneeType, CaseStatus, ItemStatus, OnboardingItemType


class TemplateItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    item_type: OnboardingItemType = OnboardingItemType.TASK
    assignee_type: AssigneeType = AssigneeType.EMPLOYEE
    # Negative = before the joining date (pre-joining tasks such as sending documents).
    due_days_from_hire: int = Field(default=7, ge=-90, le=365)
    required: bool = True
    sequence: int = 0


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    trigger: str = "HIRE"
    is_default: bool = False
    items: list[TemplateItemCreate] = []


class TemplateItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    item_type: OnboardingItemType
    assignee_type: AssigneeType
    due_days_from_hire: int
    required: bool
    sequence: int


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None
    trigger: str
    is_default: bool
    status: str
    items: list[TemplateItemResponse] = []


class CaseCreateRequest(BaseModel):
    employment_id: str
    template_id: str | None = None  # uses default if omitted
    hire_date: date


class OnboardingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    item_type: OnboardingItemType
    assignee_type: AssigneeType
    due_date: date | None
    required: bool
    sequence: int
    status: ItemStatus
    completed_at: datetime | None
    notes: str | None


class CaseResponse(BaseModel):
    id: str
    employment_id: str
    template_id: str
    status: CaseStatus
    hire_date: date
    started_at: datetime
    completed_at: datetime | None
    items: list[OnboardingItemResponse] = []
    # Summary counts
    total_items: int = 0
    completed_items: int = 0
    overdue_items: int = 0


class ItemUpdateRequest(BaseModel):
    status: ItemStatus
    notes: str | None = None
    document_key: str | None = None

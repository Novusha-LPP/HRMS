from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from hrms.modules.onboarding.models import AssigneeType, CaseStatus, ItemStatus, OnboardingItemType


class TemplateItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    item_type: OnboardingItemType = OnboardingItemType.TASK
    assignee_type: AssigneeType = AssigneeType.EMPLOYEE
    due_days_from_hire: int = 7
    required: bool = True
    sequence: int = 0


class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger: str = "HIRE"
    is_default: bool = False
    items: list[TemplateItemCreate] = []


class TemplateItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str]
    item_type: OnboardingItemType
    assignee_type: AssigneeType
    due_days_from_hire: int
    required: bool
    sequence: int


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    trigger: str
    is_default: bool
    status: str
    items: list[TemplateItemResponse] = []


class CaseCreateRequest(BaseModel):
    employment_id: str
    template_id: Optional[str] = None  # uses default if omitted
    hire_date: date


class OnboardingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str]
    item_type: OnboardingItemType
    assignee_type: AssigneeType
    due_date: Optional[date]
    required: bool
    sequence: int
    status: ItemStatus
    completed_at: Optional[datetime]
    notes: Optional[str]


class CaseResponse(BaseModel):
    id: str
    employment_id: str
    template_id: str
    status: CaseStatus
    hire_date: date
    started_at: datetime
    completed_at: Optional[datetime]
    items: list[OnboardingItemResponse] = []
    # Summary counts
    total_items: int = 0
    completed_items: int = 0
    overdue_items: int = 0


class ItemUpdateRequest(BaseModel):
    status: ItemStatus
    notes: Optional[str] = None
    document_key: Optional[str] = None

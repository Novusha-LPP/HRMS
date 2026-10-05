from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RequestType = Literal[
    "LEAVE", "LEAVE_CANCELLATION", "CORRECTION", "OVERTIME", "JOB_REQUISITION"
]


class StepSpec(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    approver_ids: list[str] = Field(default_factory=list, max_length=50)
    approver_source: Literal["PEOPLE", "TEAM_LEAD", "TEAM_PM"] = "PEOPLE"

    @model_validator(mode="after")
    def approvers(self):
        if self.approver_source == "PEOPLE" and not self.approver_ids:
            raise ValueError("Choose at least one approver")
        if self.approver_source != "PEOPLE" and self.approver_ids:
            raise ValueError("Team role stages cannot also select people")
        return self


class FlowWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=150)
    request_type: RequestType
    org_unit_id: str | None = None
    employment_id: str | None = None

    @model_validator(mode="after")
    def target(self):
        if self.org_unit_id and self.employment_id:
            raise ValueError("Choose a department/team or an individual")
        if self.reusable and (self.org_unit_id or self.employment_id):
            raise ValueError("Assign reusable workflows from the employee profile")
        if self.reusable and any(s.approver_source != "PEOPLE" for s in self.steps):
            raise ValueError("Reusable workflows use selected people, independent of team roles")
        return self

    reusable: bool = True
    enabled: bool = True
    steps: list[StepSpec] = Field(min_length=1, max_length=50)
    version: int | None = Field(default=None, ge=1)


class EmployeeFlowWrite(BaseModel):
    flow_id: str | None = None
    version: int = Field(ge=0)


class DelegationWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    instance_id: str
    level: int = Field(ge=1)
    original_user_id: str
    delegate_user_id: str
    # Request-only unless a workflow administrator explicitly enables flow-wide scope.
    flow_wide: bool = False
    valid_from: datetime
    valid_until: datetime
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("Include a timezone offset")
        return v

    @model_validator(mode="after")
    def ordered(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("Delegation end must follow its start")
        if self.original_user_id == self.delegate_user_id:
            raise ValueError("Delegate must be a different account")
        return self


class Decision(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    comments: str | None = Field(default=None, max_length=1000)

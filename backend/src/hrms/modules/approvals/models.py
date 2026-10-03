"""Configurable routes, immutable request snapshots and audited delegation."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ApprovalFlow(SQLModel, table=True):
    __tablename__ = "approval_flows"
    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    name: str = Field(max_length=150)
    request_type: str = Field(max_length=30)
    org_unit_id: UUID | None = Field(default=None)
    employment_id: UUID | None = Field(default=None)
    reusable: bool = Field(default=False)
    owner_employment_id: UUID | None = Field(default=None)
    legal_entity_id: UUID | None = Field(default=None)
    enabled: bool = Field(default=True)
    steps: list[dict] = Field(sa_column=Column(JSONB, nullable=False))
    version: int = Field(default=1)
    updated_by: UUID = Field()
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EmployeeApprovalFlow(SQLModel, table=True):
    __tablename__ = "employee_approval_flows"
    tenant_id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(primary_key=True)
    request_type: str = Field(primary_key=True, max_length=30)
    flow_id: UUID | None = Field(default=None)
    version: int = Field(default=1)
    updated_by: UUID = Field()
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalInstance(SQLModel, table=True):
    __tablename__ = "approval_instances"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "request_type",
            "request_id",
            "generation",
            name="uq_approval_instance_generation",
        ),
    )
    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    flow_id: UUID = Field()
    request_type: str = Field(max_length=30)
    request_id: UUID = Field()
    employment_id: UUID = Field()
    generation: int = Field(default=1)
    flow_version: int = Field()
    steps: list[dict] = Field(sa_column=Column(JSONB, nullable=False))
    current_level: int = Field(default=1)
    status: str = Field(default="PENDING", max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalDelegation(SQLModel, table=True):
    __tablename__ = "approval_delegations"
    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    flow_id: UUID = Field()
    instance_id: UUID | None = Field(default=None)
    step_id: UUID = Field()
    original_user_id: UUID = Field()
    delegate_user_id: UUID = Field()
    valid_from: datetime = Field()
    valid_until: datetime = Field()
    reason: str = Field(max_length=1000)
    created_by: UUID = Field()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = Field(default=None)
    revoked_by: UUID | None = Field(default=None)


class ApprovalEvent(SQLModel, table=True):
    __tablename__ = "approval_events"
    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    flow_id: UUID = Field()
    instance_id: UUID | None = Field(default=None)
    actor_user_id: UUID | None = Field(default=None)
    action: str = Field(max_length=30)
    details: dict = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

"""
One row per job run, so "when did accrual last succeed?" is a query, not a guess: /metrics
exports it (hrms_job_last_success_timestamp_seconds) and an alert fires when it goes stale.
Platform-wide like `tenants`, so no RLS; the detail never holds personal data.
"""
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class JobRun(SQLModel, table=True):
    __tablename__ = "job_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job: str = Field(max_length=60, index=True)
    status: str = Field(max_length=20)  # RUNNING | SUCCEEDED | FAILED
    started_at: datetime = Field(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False))
    finished_at: datetime | None = Field(
        default=None, sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True)
    )
    tenants_ok: int = 0
    tenants_failed: int = 0
    detail: str | None = Field(default=None, max_length=2000)

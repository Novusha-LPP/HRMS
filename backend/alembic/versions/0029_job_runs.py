"""Record scheduled job runs (hrms.jobs)

One row per run of a daily job, so the last success of each job is exported by /metrics and
alerted on when it goes stale. Platform-wide like `tenants`: no tenant_id, no RLS, and the
detail column holds tenant ids and error class names only — never personal data.

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenants_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tenants_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.String(length=2000), nullable=True),
    )
    op.create_index("ix_job_runs_job", "job_runs", ["job"])
    op.create_index("ix_job_runs_job_finished", "job_runs", ["job", "finished_at"])


def downgrade() -> None:
    op.drop_table("job_runs")

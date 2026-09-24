"""Add time, onboarding and reports tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Shifts ────────────────────────────────────────────────────────────────
    op.create_table(
        "shifts",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("break_minutes", sa.Integer, nullable=False, server_default="30"),
        sa.Column("work_days", sa.Integer, nullable=False, server_default="31"),
        sa.Column("grace_late_minutes", sa.Integer, nullable=False, server_default="10"),
        sa.Column("grace_early_departure_minutes", sa.Integer, nullable=False, server_default="10"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("shifts")

    # ── Punches (append-only) ─────────────────────────────────────────────────
    op.create_table(
        "punches",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("punch_type", sa.String(20), nullable=False),
        sa.Column("punched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="WEB"),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("device_id", sa.String(100)),
        sa.Column("selfie_key", sa.String(500)),
        sa.Column("is_corrected", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("original_punch_id", UUID(as_uuid=True)),
        sa.Column("correction_reason", sa.String(255)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_punches_employment_time", "punches",
                    ["tenant_id", "employment_id", "punched_at"])
    _enable_rls("punches")

    # ── Attendance days ───────────────────────────────────────────────────────
    op.create_table(
        "attendance_days",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("work_date", sa.Date, nullable=False),
        sa.Column("shift_id", UUID(as_uuid=True)),
        sa.Column("first_punch_in", sa.DateTime(timezone=True)),
        sa.Column("last_punch_out", sa.DateTime(timezone=True)),
        sa.Column("gross_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("break_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("effective_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("late_by_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("early_departure_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "employment_id", "work_date",
                            name="uq_attendance_day"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_attendance_employment_date", "attendance_days",
                    ["tenant_id", "employment_id", "work_date"])
    _enable_rls("attendance_days")

    # ── Onboarding templates ──────────────────────────────────────────────────
    op.create_table(
        "onboarding_templates",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("trigger", sa.String(50), nullable=False, server_default="HIRE"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.String(50), nullable=False, server_default="ACTIVE"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("onboarding_templates")

    op.create_table(
        "onboarding_template_items",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("item_type", sa.String(50), nullable=False, server_default="TASK"),
        sa.Column("assignee_type", sa.String(50), nullable=False, server_default="EMPLOYEE"),
        sa.Column("due_days_from_hire", sa.Integer, nullable=False, server_default="7"),
        sa.Column("required", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("onboarding_template_items")

    op.create_table(
        "onboarding_cases",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="IN_PROGRESS"),
        sa.Column("hire_date", sa.Date, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_ob_cases_employment", "onboarding_cases", ["tenant_id", "employment_id"])
    _enable_rls("onboarding_cases")

    op.create_table(
        "onboarding_items",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", UUID(as_uuid=True), nullable=False),
        sa.Column("template_item_id", UUID(as_uuid=True)),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("item_type", sa.String(50), nullable=False),
        sa.Column("assignee_type", sa.String(50), nullable=False),
        sa.Column("due_date", sa.Date),
        sa.Column("required", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by", UUID(as_uuid=True)),
        sa.Column("document_key", sa.String(500)),
        sa.Column("notes", sa.String(1000)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_ob_items_case", "onboarding_items", ["tenant_id", "case_id"])
    _enable_rls("onboarding_items")

    # ── Report definitions ────────────────────────────────────────────────────
    op.create_table(
        "report_definitions",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("columns", sa.Text, nullable=False, server_default="[]"),
        sa.Column("filters", sa.Text, nullable=False, server_default="[]"),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("owner_type", sa.String(50), nullable=False, server_default="HR"),
        sa.Column("created_by", UUID(as_uuid=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    _enable_rls("report_definitions")


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)


def downgrade() -> None:
    for t in [
        "report_definitions", "onboarding_items", "onboarding_cases",
        "onboarding_template_items", "onboarding_templates",
        "attendance_days", "punches", "shifts",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

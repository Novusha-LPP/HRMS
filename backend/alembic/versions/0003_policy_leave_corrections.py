"""Add policy, leave, and attendance correction tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_tenant_id())")


def upgrade() -> None:
    # ── Policy templates ──────────────────────────────────────────────────────
    op.create_table(
        "policy_templates",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="'UTC'"),
        sa.Column("expected_start_time", sa.Time, nullable=False, server_default="'09:00:00'"),
        sa.Column("expected_end_time", sa.Time, nullable=False, server_default="'18:00:00'"),
        sa.Column("work_days", sa.String(7), nullable=False, server_default="'1111100'"),
        sa.Column("break_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column("break_auto_deduct", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("grace_late_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("grace_early_departure_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("half_day_threshold_pct", sa.Integer, nullable=False, server_default="50"),
        sa.Column("ot_enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("ot_qualifying_minutes", sa.Integer, nullable=False, server_default="30"),
        sa.Column("ot_rate", sa.Float, nullable=False, server_default="1.5"),
        sa.Column("ot_daily_cap_minutes", sa.Integer, nullable=True),
        sa.Column("punch_rounding_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "punch_rounding_direction", sa.String(10), nullable=False, server_default="'NONE'"
        ),
        sa.Column(
            "correction_requires_approval", sa.Boolean, nullable=False, server_default="true"
        ),
        sa.Column("correction_approval_levels", sa.Integer, nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    _enable_rls("policy_templates")

    # ── Employee policy assignments ───────────────────────────────────────────
    op.create_table(
        "employee_policy_assignments",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("policy_template_id", UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("ot_qualifying_minutes_override", sa.Integer, nullable=True),
        sa.Column("grace_late_minutes_override", sa.Integer, nullable=True),
        sa.Column("grace_early_departure_minutes_override", sa.Integer, nullable=True),
        sa.Column("ot_enabled_override", sa.Boolean, nullable=True),
        sa.Column("ot_rate_override", sa.Float, nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.Index("ix_emp_policy_asgn_emp", "tenant_id", "employment_id"),
    )
    op.create_index("ix_epa_employment", "employee_policy_assignments", ["employment_id"])
    _enable_rls("employee_policy_assignments")

    # ── Leave types ───────────────────────────────────────────────────────────
    op.create_table(
        "leave_types",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("days_per_year", sa.Float, nullable=False),
        sa.Column("carry_forward", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("max_carry_forward_days", sa.Float, nullable=True),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("approval_levels", sa.Integer, nullable=False, server_default="1"),
        sa.Column("cancel_requires_approval", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("cancel_approval_levels", sa.Integer, nullable=False, server_default="1"),
        sa.Column("min_days_per_application", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("max_days_per_application", sa.Float, nullable=True),
        sa.Column("advance_notice_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("requires_document", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_paid", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("color", sa.String(20), nullable=False, server_default="'#3B82F6'"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    _enable_rls("leave_types")

    # ── Leave balances ────────────────────────────────────────────────────────
    op.create_table(
        "leave_balances",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leave_type_id", UUID(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("allocated_days", sa.Float, nullable=False, server_default="0"),
        sa.Column("carry_forward_days", sa.Float, nullable=False, server_default="0"),
        sa.Column("used_days", sa.Float, nullable=False, server_default="0"),
        sa.Column("pending_days", sa.Float, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index(
        "ix_lb_emp_type_year", "leave_balances", ["employment_id", "leave_type_id", "year"]
    )
    _enable_rls("leave_balances")

    # ── Leave applications ────────────────────────────────────────────────────
    op.create_table(
        "leave_applications",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leave_type_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_date", sa.Date, nullable=False),
        sa.Column("to_date", sa.Date, nullable=False),
        sa.Column("days_requested", sa.Float, nullable=False),
        sa.Column("half_day_option", sa.String(15), nullable=False, server_default="'NONE'"),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("status", sa.String(25), nullable=False, server_default="'DRAFT'"),
        sa.Column("current_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_levels", sa.Integer, nullable=False, server_default="1"),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(1000), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_la_employment", "leave_applications", ["employment_id"])
    _enable_rls("leave_applications")

    # ── Leave approval actions ────────────────────────────────────────────────
    op.create_table(
        "leave_approval_actions",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(20), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("approver_employment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("comments", sa.String(1000), nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_laa_application", "leave_approval_actions", ["application_id"])
    _enable_rls("leave_approval_actions")

    # ── Attendance correction requests ────────────────────────────────────────
    op.create_table(
        "attendance_correction_requests",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("work_date", sa.Date, nullable=False),
        sa.Column("correction_type", sa.String(30), nullable=False),
        sa.Column("requested_punch_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_punch_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="'DRAFT'"),
        sa.Column("current_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_levels", sa.Integer, nullable=False, server_default="1"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_acr_employment", "attendance_correction_requests", ["employment_id"])
    op.create_index("ix_acr_date", "attendance_correction_requests", ["work_date"])
    _enable_rls("attendance_correction_requests")

    # ── Correction approval actions ───────────────────────────────────────────
    op.create_table(
        "correction_approval_actions",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("approver_employment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("comments", sa.String(1000), nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_caa_correction", "correction_approval_actions", ["correction_id"])
    _enable_rls("correction_approval_actions")


def downgrade() -> None:
    for tbl in [
        "correction_approval_actions",
        "attendance_correction_requests",
        "leave_approval_actions",
        "leave_applications",
        "leave_balances",
        "leave_types",
        "employee_policy_assignments",
        "policy_templates",
    ]:
        op.drop_table(tbl)

"""Attendance: days flagged for HR review, and work on a weekly off or holiday (OT or comp-off)."""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    # What a day worked on a weekly off or holiday earns: overtime, or a comp-off credit.
    op.add_column(
        "policy_templates",
        sa.Column("off_day_work", sa.String(10), nullable=False, server_default="OVERTIME"),
    )
    op.create_check_constraint(
        "ck_policy_templates_off_day_work",
        "policy_templates",
        "off_day_work IN ('OVERTIME', 'COMP_OFF')",
    )
    # Why a day needs HR to look at it (a break never ended, an over-long day) and who did.
    op.add_column("attendance_days", sa.Column("review_flags", sa.String(60)))
    op.add_column("attendance_days", sa.Column("reviewed_by", sa.Uuid()))
    op.add_column("attendance_days", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "attendance_days",
        sa.Column("comp_off_days", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("attendance_days", "comp_off_days")
    op.drop_column("attendance_days", "reviewed_at")
    op.drop_column("attendance_days", "reviewed_by")
    op.drop_column("attendance_days", "review_flags")
    op.drop_constraint("ck_policy_templates_off_day_work", "policy_templates")
    op.drop_column("policy_templates", "off_day_work")

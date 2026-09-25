"""Drop the unused Shift model.

Gap analysis found `shifts` (migration 0002) had no CRUD endpoints, was
never assigned to any employee (attendance_days.shift_id was always null),
and the policy engine computes expected start/end times purely from
PolicyTemplate — Shift was fully orphaned. Removing it rather than leaving
dead schema around.

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("attendance_days", "shift_id")
    op.drop_table("shifts")


def downgrade() -> None:
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
    op.execute("ALTER TABLE shifts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE shifts FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON shifts
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON shifts TO hrms_app")
    op.add_column("attendance_days", sa.Column("shift_id", UUID(as_uuid=True), nullable=True))

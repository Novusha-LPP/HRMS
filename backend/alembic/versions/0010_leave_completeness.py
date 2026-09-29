"""Round out Leave: holiday calendar, comp-off, encashment, accrual tracking.

Gap analysis found: HOLIDAY existed only as an AttendanceStatus enum value
with no table to ever set a date as one; no comp-off concept anywhere; no
leave encashment; leave balances only ever created via a one-time manual
POST /v1/leave/balances/init, no accrual automation. This migration adds
the schema for all four.

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Holiday calendar — legal_entity_id NULL means tenant-wide (applies to
    # every company); set means specific to one company (different states/
    # countries observe different holidays).
    op.create_table(
        "holidays",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("holiday_date", sa.Date, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("legal_entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_optional", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("ix_holidays_date", "holidays", ["tenant_id", "holiday_date"])
    op.execute("ALTER TABLE holidays ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE holidays FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON holidays
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)

    # Comp-off: which leave type an employee's comp-off credits land in, and
    # accrual: which leave types get a monthly automatic top-up.
    op.add_column(
        "leave_types", sa.Column("is_comp_off", sa.Boolean, nullable=False, server_default="false")
    )
    op.add_column(
        "leave_types", sa.Column("encashable", sa.Boolean, nullable=False, server_default="false")
    )
    op.add_column(
        "leave_types",
        sa.Column("accrual_enabled", sa.Boolean, nullable=False, server_default="false"),
    )

    # Idempotency for accrual: which "YYYY-MM" period this balance last got
    # its automatic credit for, so re-running the same month is a no-op.
    op.add_column("leave_balances", sa.Column("last_accrued_period", sa.String(7), nullable=True))

    op.create_table(
        "comp_off_grants",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("work_date", sa.Date, nullable=False),
        sa.Column("days_granted", sa.Float, nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("granted_by", UUID(as_uuid=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    # One grant per employee per worked day — the idempotency guard against
    # double-crediting the same day of work.
    op.create_index(
        "ix_comp_off_unique",
        "comp_off_grants",
        ["tenant_id", "employment_id", "work_date"],
        unique=True,
    )
    op.execute("ALTER TABLE comp_off_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE comp_off_grants FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON comp_off_grants
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)

    op.create_table(
        "leave_encashments",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leave_type_id", UUID(as_uuid=True), nullable=False),
        sa.Column("days", sa.Float, nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("processed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.execute("ALTER TABLE leave_encashments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leave_encashments FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON leave_encashments
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)

    for table in ("holidays", "comp_off_grants", "leave_encashments"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hrms_app")
    op.execute("GRANT SELECT, UPDATE ON leave_types TO hrms_app")
    op.execute("GRANT SELECT, UPDATE ON leave_balances TO hrms_app")


def downgrade() -> None:
    op.drop_table("leave_encashments")
    op.drop_index("ix_comp_off_unique", table_name="comp_off_grants")
    op.drop_table("comp_off_grants")
    op.drop_column("leave_balances", "last_accrued_period")
    op.drop_column("leave_types", "accrual_enabled")
    op.drop_column("leave_types", "encashable")
    op.drop_column("leave_types", "is_comp_off")
    op.drop_index("ix_holidays_date", table_name="holidays")
    op.drop_table("holidays")

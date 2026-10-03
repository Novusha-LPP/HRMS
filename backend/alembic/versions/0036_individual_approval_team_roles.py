"""Individual approval routes and configurable team leadership."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("approval_flows", sa.Column("employment_id", UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_approval_flow_employee",
        "approval_flows",
        "employments",
        ["tenant_id", "employment_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(
        "ck_approval_flow_target", "approval_flows", "org_unit_id IS NULL OR employment_id IS NULL"
    )
    op.drop_index("uq_approval_flow_default", table_name="approval_flows")
    op.create_index(
        "uq_approval_flow_default",
        "approval_flows",
        ["tenant_id", "request_type"],
        unique=True,
        postgresql_where=sa.text("org_unit_id IS NULL AND employment_id IS NULL"),
    )
    op.create_index(
        "uq_approval_flow_employee",
        "approval_flows",
        ["tenant_id", "request_type", "employment_id"],
        unique=True,
        postgresql_where=sa.text("employment_id IS NOT NULL"),
    )
    for column in ("lead_employment_id", "pm_employment_id"):
        op.add_column("org_units", sa.Column(column, UUID(as_uuid=True)))
        op.create_foreign_key(
            f"fk_org_unit_{column}",
            "org_units",
            "employments",
            ["tenant_id", column],
            ["tenant_id", "id"],
        )


def downgrade():
    for column in ("pm_employment_id", "lead_employment_id"):
        op.drop_constraint(f"fk_org_unit_{column}", "org_units", type_="foreignkey")
        op.drop_column("org_units", column)
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM approval_flows WHERE employment_id IS NOT NULL)")
        )
        .scalar()
    ):
        raise RuntimeError(
            "Individual workflows exist; retain this migration to preserve their history"
        )
    op.drop_index("uq_approval_flow_employee", table_name="approval_flows")
    op.drop_index("uq_approval_flow_default", table_name="approval_flows")
    op.create_index(
        "uq_approval_flow_default",
        "approval_flows",
        ["tenant_id", "request_type"],
        unique=True,
        postgresql_where=sa.text("org_unit_id IS NULL"),
    )
    op.drop_constraint("ck_approval_flow_target", "approval_flows", type_="check")
    op.drop_constraint("fk_approval_flow_employee", "approval_flows", type_="foreignkey")
    op.drop_column("approval_flows", "employment_id")

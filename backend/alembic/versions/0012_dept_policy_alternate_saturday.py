"""Department-level policy assignment + alternate-Saturday support.

work_days was a plain weekly bitmask that couldn't express "2nd/4th
Saturday off," and policy assignment only ever had two tiers (per-employee,
tenant default) with nothing in between for a department. This adds
saturday_pattern to PolicyTemplate and lets employee_policy_assignments
target an org_unit instead of an employment.

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "policy_templates",
        sa.Column("saturday_pattern", sa.String(20), nullable=False, server_default="ALL"),
    )

    op.alter_column("employee_policy_assignments", "employment_id", nullable=True)
    op.add_column(
        "employee_policy_assignments",
        sa.Column("org_unit_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_epa_org_unit", "employee_policy_assignments", ["org_unit_id"])
    op.create_check_constraint(
        "ck_epa_exactly_one_target",
        "employee_policy_assignments",
        "(employment_id IS NOT NULL) != (org_unit_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_epa_exactly_one_target", "employee_policy_assignments", type_="check")
    op.drop_index("ix_epa_org_unit", table_name="employee_policy_assignments")
    op.drop_column("employee_policy_assignments", "org_unit_id")
    op.alter_column("employee_policy_assignments", "employment_id", nullable=False)

    op.drop_column("policy_templates", "saturday_pattern")

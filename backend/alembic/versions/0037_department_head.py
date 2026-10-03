"""Assign department heads for workflow ownership, including unstaffed teams."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("org_units", sa.Column("head_employment_id", UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_org_unit_head_employee",
        "org_units",
        "employments",
        ["tenant_id", "head_employment_id"],
        ["tenant_id", "id"],
    )


def downgrade():
    op.drop_constraint("fk_org_unit_head_employee", "org_units", type_="foreignkey")
    op.drop_column("org_units", "head_employment_id")

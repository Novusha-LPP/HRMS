"""Preserve source leave definitions and require explicit imported applicability."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "leave_types",
        sa.Column("legacy_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("leave_bucket_policies", sa.Column("source_policy", JSONB()))


def downgrade():
    op.drop_column("leave_bucket_policies", "source_policy")
    op.drop_column("leave_types", "legacy_managed")

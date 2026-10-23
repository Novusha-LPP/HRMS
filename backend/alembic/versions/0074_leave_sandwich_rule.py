"""Add apply_sandwich_rule to leave_types and leave_bucket_policies

Revision ID: 0074
Revises: 0073
"""

import sqlalchemy as sa
from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE leave_types "
        "ADD COLUMN IF NOT EXISTS apply_sandwich_rule BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE leave_bucket_policies "
        "ADD COLUMN IF NOT EXISTS apply_sandwich_rule BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "COMMENT ON COLUMN leave_types.apply_sandwich_rule IS "
        "'When true, weekends and public holidays between leave days are also deducted as leave.'"
    )
    op.execute(
        "COMMENT ON COLUMN leave_bucket_policies.apply_sandwich_rule IS "
        "'When true, weekends and public holidays between leave days are also deducted as leave.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE leave_types DROP COLUMN IF EXISTS apply_sandwich_rule")
    op.execute("ALTER TABLE leave_bucket_policies DROP COLUMN IF EXISTS apply_sandwich_rule")

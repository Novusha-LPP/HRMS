"""Let an attendance day carry a status imported from another system.

Revision ID: 0066
Revises: 0065
"""

import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance_days", sa.Column("status_override", sa.String(20), nullable=True))
    op.add_column("attendance_days", sa.Column("override_note", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("attendance_days", "override_note")
    op.drop_column("attendance_days", "status_override")

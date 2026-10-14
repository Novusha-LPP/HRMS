"""Make reusable workflows global across companies.

Revision ID: 0065
Revises: 0064
"""

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE approval_flows SET legal_entity_id = NULL WHERE reusable = TRUE")


def downgrade() -> None:
    pass

"""Revoke platform sessions when administrator credentials change.

Revision ID: 0024
Revises: 0023
"""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_admins",
        sa.Column("token_epoch", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("platform_admins", "token_epoch")

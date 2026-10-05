"""Encrypted authenticator seeds and monotonic replay counters."""
from alembic import op
import sqlalchemy as sa
revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("user_accounts", "platform_admins"):
        op.add_column(table, sa.Column("mfa_secret", sa.Text()))
        op.add_column(table, sa.Column("mfa_pending_secret", sa.Text()))
        op.add_column(table, sa.Column("mfa_pending_at", sa.DateTime(timezone=True)))
        op.add_column(table, sa.Column("mfa_last_step", sa.Integer(), nullable=False, server_default="-1"))


def downgrade():
    raise RuntimeError("Preserve authenticator enrollment on a code rollback")

"""Persist encrypted reset-mail delivery before acknowledging a request."""
from alembic import op
import sqlalchemy as sa
revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("platform_password_reset_tokens", sa.Column("delivery_payload", sa.Text()))
    op.add_column("platform_password_reset_tokens", sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("platform_password_reset_tokens", sa.Column("delivery_next_at", sa.DateTime(timezone=True)))
    op.add_column("platform_password_reset_tokens", sa.Column("delivered_at", sa.DateTime(timezone=True)))

def downgrade():
    raise RuntimeError("Checkpoint and pending reset delivery history must survive code rollback")

"""leave_bucket_policies gets a version, like every other editable master record.

docs/database-hardening-plan.md, W6: an edit carries the version it was based on, and a stale
one is refused (core/versioning.require_version). This was the one edited table without it.

Revision ID: 0063
Revises: 0062
"""

from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE leave_bucket_policies ADD COLUMN version integer NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE leave_bucket_policies DROP COLUMN version")

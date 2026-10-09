"""Holidays entered in the holiday list apply only through the calendars that include them.

Before this, a holiday on no calendar applied to everyone. The holiday list (step 1 of setting
up holidays) needs holidays that exist before any calendar uses them, so they are marked
is_library; only unmarked holidays on no calendar still apply to everyone.
"""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "holidays",
        sa.Column("is_library", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Every holiday a calendar already uses belongs to the holiday list.
    op.execute("""
        UPDATE holidays h SET is_library = true
        WHERE h.calendar_id IS NOT NULL
           OR EXISTS (SELECT 1 FROM holiday_calendar_days d
                      WHERE d.tenant_id = h.tenant_id AND d.holiday_id = h.id)
    """)


def downgrade():
    op.drop_column("holidays", "is_library")

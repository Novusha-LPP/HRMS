"""Make overtime real: persist the already-computed OT minutes, add a review step.

core/datetime_utils.compute_day() has always correctly computed ot_minutes
from the policy engine (ot_enabled, ot_qualifying_minutes, ot_daily_cap_minutes)
— but attendance_days had no column for it, so both call sites (time/router.py
punch-out, corrections/router.py post-approval recompute) silently discarded
the value. Meanwhile the daily-analysis endpoint showed a completely
different, hardcoded `max(0, effective - 480)` flat-8-hour number under the
label "Approved Overtime" despite no approval step existing anywhere. This
migration adds the missing column plus a genuine PENDING/APPROVED/REJECTED
review flow so that label finally means something.

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance_days", sa.Column("ot_minutes", sa.Integer, nullable=False, server_default="0"))
    op.add_column("attendance_days", sa.Column("ot_status", sa.String(20), nullable=False, server_default="NONE"))
    op.add_column("attendance_days", sa.Column("ot_reviewed_by", UUID(as_uuid=True), nullable=True))
    op.add_column("attendance_days", sa.Column("ot_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attendance_days", sa.Column("ot_review_notes", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("attendance_days", "ot_review_notes")
    op.drop_column("attendance_days", "ot_reviewed_at")
    op.drop_column("attendance_days", "ot_reviewed_by")
    op.drop_column("attendance_days", "ot_status")
    op.drop_column("attendance_days", "ot_minutes")

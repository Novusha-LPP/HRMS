"""Rename leave_applications.days_by_year -> days_by_month

The bucket/ledger/journal engine (migration 0020) keys the monthly ledger by
(calendar_year, calendar_month) — a leave application spanning a month
boundary now needs to post one transaction per *month* segment, not per
calendar year, so the per-application day breakdown this column stores has
to be keyed the same way. This migration only renames the column; the
application layer (leave/router.py) is what actually changes the key format
from "YYYY" to "YYYY-MM" — see the follow-up commit wiring the engine into
every leave-balance write path.

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("leave_applications", "days_by_year", new_column_name="days_by_month")


def downgrade() -> None:
    op.alter_column("leave_applications", "days_by_month", new_column_name="days_by_year")

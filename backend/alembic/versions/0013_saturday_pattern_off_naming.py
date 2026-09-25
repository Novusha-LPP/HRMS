"""Rename saturday_pattern values to "which Saturdays are off" naming.

0012 shipped saturday_pattern with FIRST_THIRD/SECOND_FOURTH meaning
"only these Saturdays work" — backwards from how "alternate Saturday" is
actually described in a policy (2nd/4th *off*, not 2nd/4th working), and
it silently left a 5th Saturday off in both cases. Renaming to
SECOND_FOURTH_OFF / FIRST_THIRD_OFF (which are OFF, not which work) makes
a 5th Saturday — never named as off — a working day by default, matching
convention. NONE is dropped: it duplicated turning Saturday off in
work_days directly, so any row using it is migrated to that instead.

No schema change — saturday_pattern was never DB-constrained to a fixed
set of values, so this is a data-only migration.

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old FIRST_THIRD ("only 1st/3rd work") is closest to new
    # SECOND_FOURTH_OFF ("2nd/4th off, 1st/3rd/5th work").
    op.execute("UPDATE policy_templates SET saturday_pattern = 'SECOND_FOURTH_OFF' WHERE saturday_pattern = 'FIRST_THIRD'")
    # Old SECOND_FOURTH ("only 2nd/4th work") is closest to new
    # FIRST_THIRD_OFF ("1st/3rd off, 2nd/4th/5th work").
    op.execute("UPDATE policy_templates SET saturday_pattern = 'FIRST_THIRD_OFF' WHERE saturday_pattern = 'SECOND_FOURTH'")
    # Old NONE ("no Saturday ever") is now expressed by turning the
    # Saturday bit of work_days off directly, not by this field.
    op.execute("""
        UPDATE policy_templates
        SET saturday_pattern = 'ALL',
            work_days = overlay(work_days placing '0' from 6 for 1)
        WHERE saturday_pattern = 'NONE'
    """)


def downgrade() -> None:
    op.execute("UPDATE policy_templates SET saturday_pattern = 'FIRST_THIRD' WHERE saturday_pattern = 'SECOND_FOURTH_OFF'")
    op.execute("UPDATE policy_templates SET saturday_pattern = 'SECOND_FOURTH' WHERE saturday_pattern = 'FIRST_THIRD_OFF'")

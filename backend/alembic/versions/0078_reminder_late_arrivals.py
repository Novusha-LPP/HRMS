"""Scheduled mail: a daily list of people who arrived late.

Expand only:

- the trigger list gains LATE_ARRIVAL. It is read from attendance_days.late_by_minutes, which
  the attendance policy already computes (grace period included), so there is no second
  definition of "late";
- reminder_rules.min_late_minutes: only people at least this many minutes late are listed.

Revision ID: 0078
Revises: 0077
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None

OLD_TRIGGERS = ("BIRTHDAY", "WORK_ANNIVERSARY", "NEW_JOINER", "EXIT")
NEW_TRIGGERS = (*OLD_TRIGGERS, "LATE_ARRIVAL")


def _trigger_check(triggers: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE reminder_rules DROP CONSTRAINT ck_reminder_rules_trigger")
    op.execute(
        "ALTER TABLE reminder_rules ADD CONSTRAINT ck_reminder_rules_trigger "
        f"CHECK ({kit.check_in('trigger', triggers)})"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE reminder_rules ADD COLUMN min_late_minutes smallint NOT NULL DEFAULT 1")
    op.execute(
        "ALTER TABLE reminder_rules ADD CONSTRAINT ck_reminder_rules_min_late "
        "CHECK (min_late_minutes BETWEEN 1 AND 600)"
    )
    _trigger_check(NEW_TRIGGERS)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM reminder_rules WHERE trigger = 'LATE_ARRIVAL') THEN
            RAISE EXCEPTION 'late-arrival rules exist; they cannot be rolled back';
          END IF;
        END $$
        """
    )
    _trigger_check(OLD_TRIGGERS)
    op.execute("ALTER TABLE reminder_rules DROP CONSTRAINT ck_reminder_rules_min_late")
    op.execute("ALTER TABLE reminder_rules DROP COLUMN min_late_minutes")

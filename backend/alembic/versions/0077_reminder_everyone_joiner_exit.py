"""Reminders: tell everyone, and remind about new joiners and exits.

Expand only:

- reminder_rules.notify_everyone: also mail every employee with an email address (within the
  rule's company and department), leaving out the person the reminder is about;
- the trigger list gains NEW_JOINER (from employments.hire_date) and EXIT (from
  employments.separation_date). Unlike a birthday these are one-off dates;
- a rule must still tell somebody, now counting notify_everyone.

Revision ID: 0077
Revises: 0076
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

OLD_TRIGGERS = ("BIRTHDAY", "WORK_ANNIVERSARY")
NEW_TRIGGERS = (*OLD_TRIGGERS, "NEW_JOINER", "EXIT")


def _replace_checks(triggers: tuple[str, ...], audience: str) -> None:
    op.execute("ALTER TABLE reminder_rules DROP CONSTRAINT ck_reminder_rules_trigger")
    op.execute("ALTER TABLE reminder_rules DROP CONSTRAINT ck_reminder_rules_audience")
    op.execute(
        "ALTER TABLE reminder_rules ADD CONSTRAINT ck_reminder_rules_trigger "
        f"CHECK ({kit.check_in('trigger', triggers)})"
    )
    op.execute(
        f"ALTER TABLE reminder_rules ADD CONSTRAINT ck_reminder_rules_audience CHECK ({audience})"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE reminder_rules ADD COLUMN notify_everyone boolean NOT NULL DEFAULT false"
    )
    _replace_checks(
        NEW_TRIGGERS,
        "notify_employee OR notify_manager OR notify_everyone OR cardinality(extra_emails) > 0",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM reminder_rules
                     WHERE notify_everyone OR trigger IN ('NEW_JOINER', 'EXIT')) THEN
            RAISE EXCEPTION 'rules use everyone or joiner/exit; cannot roll back';
          END IF;
        END $$
        """
    )
    _replace_checks(
        OLD_TRIGGERS, "notify_employee OR notify_manager OR cardinality(extra_emails) > 0"
    )
    op.execute("ALTER TABLE reminder_rules DROP COLUMN notify_everyone")

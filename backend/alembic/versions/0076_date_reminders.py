"""Date reminders: scheduled birthday and work-anniversary emails.

HR defines rules (which event, how many days ahead, how often, at what time, who is told and
with what wording). A tick job queues the mails that are due and a delivery job sends them.
Expand only:

- reminder_rules: one rule per row, company/department optional. The wording lives on the rule
  (subject and HTML body, one pair for the person themselves and one for the people told about
  them); the trigger date is derived from persons.date_of_birth or employments.hire_date, so
  there is no new date to keep in step. The API records each edit in entity_change_log.
- reminder_outbox: one row per mail to send. (rule, key) is unique, so a restarted or
  duplicated tick cannot queue the same mail twice. The people are stored as a payload and the
  mail is worded at delivery, so an edit to the wording applies to mail not yet sent.

Revision ID: 0076
Revises: 0075
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for sql in kit.tenant_table(
        "reminder_rules",
        f"""
        name varchar(120) NOT NULL,
        trigger varchar(20) NOT NULL,
        legal_entity_id uuid,
        org_unit_id uuid,
        frequency varchar(20) NOT NULL,
        days_before smallint NOT NULL DEFAULT 0,
        custom_offsets smallint[] NOT NULL DEFAULT '{{}}',
        send_time time NOT NULL,
        notify_employee boolean NOT NULL DEFAULT false,
        notify_manager boolean NOT NULL DEFAULT false,
        extra_emails text[] NOT NULL DEFAULT '{{}}',
        digest boolean NOT NULL DEFAULT true,
        subject varchar(300) NOT NULL,
        body_html text NOT NULL,
        employee_subject varchar(300) NOT NULL,
        employee_body_html text NOT NULL,
        is_active boolean NOT NULL DEFAULT true,
        last_run_date date,
        version integer NOT NULL DEFAULT 0,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_by uuid,
        updated_at timestamptz NOT NULL DEFAULT now(),
        archived_at timestamptz,
        CONSTRAINT ck_reminder_rules_trigger
            CHECK ({kit.check_in("trigger", ("BIRTHDAY", "WORK_ANNIVERSARY"))}),
        CONSTRAINT ck_reminder_rules_frequency CHECK ({
            kit.check_in(
                "frequency",
                ("SAME_DAY", "ONE_DAY_BEFORE", "CONTINUOUS", "ALTERNATE_DAYS", "CUSTOM"),
            )
        }),
        CONSTRAINT ck_reminder_rules_days_before CHECK (days_before BETWEEN 0 AND 60),
        CONSTRAINT ck_reminder_rules_audience CHECK (
            notify_employee OR notify_manager OR cardinality(extra_emails) > 0)
        """,
        comment=(
            "A birthday or work-anniversary reminder: when it runs, who is told, and the "
            "wording. last_run_date is the local date it last queued mail for."
        ),
        references={
            "legal_entity_id": "legal_entities",
            "org_unit_id": "org_units",
            "created_by": "user_accounts",
            "updated_by": "user_accounts",
        },
    ):
        op.execute(sql)

    for sql in kit.tenant_table(
        "reminder_outbox",
        f"""
        rule_id uuid NOT NULL,
        send_date date NOT NULL,
        audience varchar(10) NOT NULL,
        recipient_email varchar(320) NOT NULL,
        dedupe_key varchar(200) NOT NULL,
        payload jsonb NOT NULL,
        status varchar(10) NOT NULL DEFAULT 'PENDING',
        attempts smallint NOT NULL DEFAULT 0,
        next_attempt_at timestamptz,
        sent_at timestamptz,
        last_error varchar(200),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_reminder_outbox_audience
            CHECK ({kit.check_in("audience", ("EMPLOYEE", "TEAM"))}),
        CONSTRAINT ck_reminder_outbox_status
            CHECK ({kit.check_in("status", ("PENDING", "SENT", "FAILED"))}),
        CONSTRAINT uq_reminder_outbox_key UNIQUE (tenant_id, rule_id, dedupe_key)
        """,
        comment=(
            "Reminder mails queued for delivery. The people are kept as a payload and the mail "
            "is worded when it is sent. FAILED means every attempt was used."
        ),
        references={"rule_id": "reminder_rules"},
    ):
        op.execute(sql)
    # uq_reminder_outbox_key starts with (tenant_id, rule_id), so it serves the rule_id foreign
    # key; the index the kit made for it would be a duplicate.
    op.execute("DROP INDEX ix_reminder_outbox_rule_id")
    op.execute(
        kit.index(
            "reminder_outbox",
            ["tenant_id", "next_attempt_at"],
            name="ix_reminder_outbox_pending",
            where="status = 'PENDING'",
        )
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM reminder_rules) THEN
            RAISE EXCEPTION 'reminder rules exist; they cannot be rolled back';
          END IF;
        END $$
        """
    )
    op.execute("DROP TABLE reminder_outbox")
    op.execute("DROP TABLE reminder_rules")

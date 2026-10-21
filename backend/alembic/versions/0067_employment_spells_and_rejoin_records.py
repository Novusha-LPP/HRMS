"""Remember each stint of an employment, and what was decided when someone rejoined.

docs/REJOIN_DEVELOPMENT_PLAN.md, R1. Expand only: two new tenant tables and two new columns on
employments. Nothing reads them yet, so the previous release keeps working against this schema.

* employments.continuity_start_date: the date service is counted from (leave eligibility,
  gratuity). Starts equal to hire_date; a "start fresh" rejoin will move it.
* employments.current_spell_no: which stint is open now (1 for everyone to begin with).
* employment_spells: one row per stint (joined, left, why). Every existing employment gets
  spell 1, so history is complete from day one.
* rejoin_records: one row per rejoin, with the Continue / Start fresh decision and its reason.

Revision ID: 0067
Revises: 0066
"""

import sqlalchemy as sa
from alembic import op

from hrms.db import migration_kit as kit

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employments", sa.Column("continuity_start_date", sa.Date(), nullable=True))
    op.add_column(
        "employments",
        sa.Column("current_spell_no", sa.Integer(), nullable=False, server_default="1"),
    )

    for sql in kit.tenant_table(
        "employment_spells",
        """
        employment_id uuid NOT NULL,
        spell_no integer NOT NULL,
        joined_on date NOT NULL,
        left_on date,
        exit_reason varchar(100),
        gratuity_paid boolean,
        leave_settled boolean NOT NULL DEFAULT false,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_employment_spells_number UNIQUE (tenant_id, employment_id, spell_no),
        CONSTRAINT ck_employment_spells_number CHECK (spell_no >= 1),
        CONSTRAINT ck_employment_spells_dates CHECK (left_on IS NULL OR left_on >= joined_on)
        """,
        comment=(
            "One stint of an employment: when the person joined and left. A rejoin opens the "
            "next stint; the employment record itself is reused."
        ),
        references={"employment_id": "employments", "created_by": "user_accounts"},
    ):
        op.execute(sql)

    # The unique key leads with (tenant_id, employment_id), so it already serves the foreign key.
    op.execute("DROP INDEX ix_employment_spells_employment_id")

    for sql in kit.tenant_table(
        "rejoin_records",
        f"""
        employment_id uuid NOT NULL,
        personnel_action_id uuid,
        previous_spell_id uuid,
        new_spell_id uuid,
        mode varchar(10) NOT NULL,
        break_start date,
        break_end date,
        break_condoned boolean NOT NULL DEFAULT false,
        reason text,
        approved_by uuid,
        restored_leave jsonb,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_rejoin_records_mode CHECK ({kit.check_in("mode", ("CONTINUE", "FRESH"))}),
        CONSTRAINT ck_rejoin_records_break CHECK (
            break_start IS NULL OR break_end IS NULL OR break_end >= break_start
        )
        """,
        comment=(
            "What was decided when a separated employee rejoined: keep earlier service and "
            "leave (CONTINUE) or start over (FRESH), who approved it, and why."
        ),
        references={
            "employment_id": "employments",
            "personnel_action_id": "personnel_actions",
            "previous_spell_id": "employment_spells",
            "new_spell_id": "employment_spells",
            "approved_by": "user_accounts",
            "created_by": "user_accounts",
        },
    ):
        op.execute(sql)

    # Backfill runs as the table owner, which forced row-level security would otherwise filter.
    for table in ("employments", "employment_spells"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE employments SET continuity_start_date = hire_date")
    op.execute(
        """
        INSERT INTO employment_spells
            (tenant_id, id, employment_id, spell_no, joined_on, left_on, leave_settled)
        SELECT tenant_id, gen_random_uuid(), id, 1, hire_date, separation_date, false
        FROM employments
        """
    )
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    for table in ("employments", "employment_spells"):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE rejoin_records")
    op.execute("DROP TABLE employment_spells")
    op.drop_column("employments", "current_spell_no")
    op.drop_column("employments", "continuity_start_date")

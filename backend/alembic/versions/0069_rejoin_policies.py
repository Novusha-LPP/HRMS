"""Company rules for rejoining: the default choice, and how long a break can be and still continue.

docs/REJOIN_DEVELOPMENT_PLAN.md, R3. Expand only: one new tenant table, and one more allowed
value for leave_balance_transactions.reference_type (leave closed when a rejoin starts fresh).

A company, or every company when none is named, sets from a date:
* default_mode: CONTINUE (earlier service and held leave carry on) or FRESH (start over);
* force_fresh_after_days: a break longer than this can only continue if HR records that it was
  condoned, with a reason.
No policy means CONTINUE with no limit, which is how rejoining works today.

Revision ID: 0069
Revises: 0068
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None

OLD_REFERENCES = (
    "ACCRUAL_RUN",
    "COMP_OFF",
    "ENCASHMENT",
    "LEAVE_APPLICATION",
    "MANUAL",
    "SEPARATION",
    "YEAR_END",
)
NEW_REFERENCES = (*OLD_REFERENCES, "REJOIN")
CONSTRAINT = "ck_leave_balance_transactions_reference_type"


def upgrade() -> None:
    for sql in kit.tenant_table(
        "rejoin_policies",
        f"""
        legal_entity_id uuid,
        default_mode varchar(10) NOT NULL,
        force_fresh_after_days integer,
        effective_from date NOT NULL,
        archived_at timestamptz,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_rejoin_policies_mode CHECK ({kit.check_in("default_mode", ("CONTINUE", "FRESH"))}),
        CONSTRAINT ck_rejoin_policies_days
            CHECK (force_fresh_after_days IS NULL OR force_fresh_after_days >= 0)
        """,
        comment=(
            "How a company treats someone who rejoins: continue earlier service by default or "
            "start fresh, and how long a break can be before it must start fresh."
        ),
        references={"legal_entity_id": "legal_entities", "created_by": "user_accounts"},
    ):
        op.execute(sql)
    op.execute(
        "CREATE UNIQUE INDEX uq_rejoin_policies_scope ON rejoin_policies "
        "(tenant_id, COALESCE(legal_entity_id, '00000000-0000-0000-0000-000000000000'), "
        "effective_from) WHERE archived_at IS NULL"
    )
    op.execute(f"ALTER TABLE leave_balance_transactions DROP CONSTRAINT {CONSTRAINT}")
    for sql in kit.add_check(
        "leave_balance_transactions", CONSTRAINT, kit.check_in("reference_type", NEW_REFERENCES)
    ):
        op.execute(sql)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM leave_balance_transactions WHERE reference_type = 'REJOIN') THEN
            RAISE EXCEPTION 'rejoin leave entries exist in the ledger; they cannot be rolled back';
          END IF;
        END $$
        """
    )
    op.execute(f"ALTER TABLE leave_balance_transactions DROP CONSTRAINT {CONSTRAINT}")
    for sql in kit.add_check(
        "leave_balance_transactions", CONSTRAINT, kit.check_in("reference_type", OLD_REFERENCES)
    ):
        op.execute(sql)
    op.execute("DROP TABLE rejoin_policies")

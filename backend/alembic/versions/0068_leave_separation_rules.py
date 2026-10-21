"""What happens to unused leave when someone leaves.

docs/REJOIN_DEVELOPMENT_PLAN.md, R2. Expand only: two new tenant tables, and one more allowed
value for leave_balance_transactions.reference_type.

* leave_separation_rules: per company and leave type (either can be "any"), from a date, what
  to do with the unused balance on separation: LAPSE it, ENCASH it, or HOLD it (optionally for
  a number of days, so a quick return can still get it back). No rule means nothing happens,
  which is how every company behaves today.
* leave_separation_settlements: what was done for one leave balance when one stint ended (how many days
  were encashed, lapsed or are still held). One row per (stint, balance) so running the settlement twice changes nothing.

Revision ID: 0068
Revises: 0067
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

OLD_REFERENCES = (
    "ACCRUAL_RUN",
    "COMP_OFF",
    "ENCASHMENT",
    "LEAVE_APPLICATION",
    "MANUAL",
    "YEAR_END",
)
NEW_REFERENCES = (*OLD_REFERENCES, "SEPARATION")
CONSTRAINT = "ck_leave_balance_transactions_reference_type"


def upgrade() -> None:
    for sql in kit.tenant_table(
        "leave_separation_rules",
        f"""
        legal_entity_id uuid,
        leave_type_id uuid,
        on_separation varchar(10) NOT NULL,
        hold_days integer,
        max_encash_days numeric(6,1),
        effective_from date NOT NULL,
        archived_at timestamptz,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_leave_separation_rules_action
            CHECK ({kit.check_in("on_separation", ("LAPSE", "ENCASH", "HOLD"))}),
        CONSTRAINT ck_leave_separation_rules_hold CHECK (hold_days IS NULL OR hold_days >= 0),
        CONSTRAINT ck_leave_separation_rules_hold_only
            CHECK (hold_days IS NULL OR on_separation = 'HOLD'),
        CONSTRAINT ck_leave_separation_rules_encash
            CHECK (max_encash_days IS NULL OR (max_encash_days >= 0 AND {kit.half_day("max_encash_days")})),
        CONSTRAINT ck_leave_separation_rules_encash_only
            CHECK (max_encash_days IS NULL OR on_separation = 'ENCASH')
        """,
        comment=(
            "What to do with unused leave when someone leaves, for a company and leave type "
            "(either may be 'any') from a date. The most specific rule in force applies."
        ),
        references={
            "legal_entity_id": "legal_entities",
            "leave_type_id": "leave_types",
            "created_by": "user_accounts",
        },
    ):
        op.execute(sql)
    op.execute(
        "CREATE UNIQUE INDEX uq_leave_separation_rules_scope ON leave_separation_rules "
        "(tenant_id, COALESCE(legal_entity_id, '00000000-0000-0000-0000-000000000000'), "
        "COALESCE(leave_type_id, '00000000-0000-0000-0000-000000000000'), effective_from) "
        "WHERE archived_at IS NULL"
    )

    for sql in kit.tenant_table(
        "leave_separation_settlements",
        f"""
        employment_id uuid NOT NULL,
        spell_id uuid NOT NULL,
        leave_type_id uuid NOT NULL,
        bucket_id uuid NOT NULL,
        days numeric(6,1) NOT NULL,
        encashed_days numeric(6,1) NOT NULL DEFAULT 0,
        lapsed_days numeric(6,1) NOT NULL DEFAULT 0,
        action varchar(10) NOT NULL,
        settled_on date NOT NULL,
        balance_transaction_id uuid,
        hold_expires_on date,
        resolution varchar(10),
        resolved_on date,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_leave_separation_settlements_balance
            UNIQUE (tenant_id, spell_id, bucket_id),
        CONSTRAINT ck_leave_separation_settlements_action
            CHECK ({kit.check_in("action", ("LAPSE", "ENCASH", "HOLD"))}),
        CONSTRAINT ck_leave_separation_settlements_resolution
            CHECK (resolution IS NULL OR {kit.check_in("resolution", ("LAPSED", "RESTORED"))}),
        CONSTRAINT ck_leave_separation_settlements_days CHECK (
            days >= 0 AND encashed_days >= 0 AND lapsed_days >= 0
            AND encashed_days + lapsed_days <= days
            AND {kit.half_day("days")} AND {kit.half_day("encashed_days")}
            AND {kit.half_day("lapsed_days")}
        )
        """,
        comment=(
            "What was done with one leave balance when one stint of an employment ended: "
            "lapsed, encashed, or held (and later lapsed or restored on a rejoin)."
        ),
        references={
            "employment_id": "employments",
            "spell_id": "employment_spells",
            "leave_type_id": "leave_types",
            "bucket_id": "leave_balance_buckets",
            "balance_transaction_id": "leave_balance_transactions",
            "created_by": "user_accounts",
        },
    ):
        op.execute(sql)

    # The unique key leads with (tenant_id, spell_id), so it already serves that foreign key.
    op.execute("DROP INDEX ix_leave_separation_settlements_spell_id")

    op.execute(f"ALTER TABLE leave_balance_transactions DROP CONSTRAINT {CONSTRAINT}")
    for sql in kit.add_check(
        "leave_balance_transactions", CONSTRAINT, kit.check_in("reference_type", NEW_REFERENCES)
    ):
        op.execute(sql)


def downgrade() -> None:
    # The ledger is history and cannot be rewritten from here; refuse rather than orphan it.
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM leave_balance_transactions
                     WHERE reference_type = 'SEPARATION') THEN
            RAISE EXCEPTION 'leave settlements exist in the ledger; they cannot be rolled back';
          END IF;
        END $$
        """
    )
    op.execute(f"ALTER TABLE leave_balance_transactions DROP CONSTRAINT {CONSTRAINT}")
    for sql in kit.add_check(
        "leave_balance_transactions", CONSTRAINT, kit.check_in("reference_type", OLD_REFERENCES)
    ):
        op.execute(sql)
    op.execute("DROP TABLE leave_separation_settlements")
    op.execute("DROP TABLE leave_separation_rules")

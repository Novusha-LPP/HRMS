"""Moving a person from one company of the group to another.

docs/REJOIN_DEVELOPMENT_PLAN.md, R7. Expand only: one new tenant table, and one more allowed
value for leave_balance_transactions.reference_type (leave carried to the new company).

A transfer ends the employment in the first company and starts a new one in the second, on the
same day. Each side keeps its own history; this row ties the two together and records what was
done with the leave.

Revision ID: 0071
Revises: 0070
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None

OLD_REFERENCES = (
    "ACCRUAL_RUN",
    "COMP_OFF",
    "ENCASHMENT",
    "LEAVE_APPLICATION",
    "MANUAL",
    "REJOIN",
    "SEPARATION",
    "YEAR_END",
)
NEW_REFERENCES = (*OLD_REFERENCES, "TRANSFER")
CONSTRAINT = "ck_leave_balance_transactions_reference_type"


def upgrade() -> None:
    for sql in kit.tenant_table(
        "company_transfers",
        f"""
        person_id uuid NOT NULL,
        from_employment_id uuid NOT NULL,
        to_employment_id uuid NOT NULL,
        effective_date date NOT NULL,
        leave_mode varchar(10) NOT NULL,
        reason text,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_company_transfers_mode CHECK ({kit.check_in("leave_mode", ("CARRY", "SETTLE"))}),
        CONSTRAINT ck_company_transfers_distinct CHECK (from_employment_id <> to_employment_id)
        """,
        comment=(
            "A person moved from one company of the group to another: the employment they left, "
            "the one they joined, when, and whether leave was carried over or settled."
        ),
        references={
            "person_id": "persons",
            "from_employment_id": "employments",
            "to_employment_id": "employments",
            "created_by": "user_accounts",
        },
    ):
        op.execute(sql)
    op.execute(f"ALTER TABLE leave_balance_transactions DROP CONSTRAINT {CONSTRAINT}")
    for sql in kit.add_check(
        "leave_balance_transactions", CONSTRAINT, kit.check_in("reference_type", NEW_REFERENCES)
    ):
        op.execute(sql)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM leave_balance_transactions WHERE reference_type = 'TRANSFER') THEN
            RAISE EXCEPTION 'transfer leave entries exist in the ledger; they cannot be rolled back';
          END IF;
        END $$
        """
    )
    op.execute(f"ALTER TABLE leave_balance_transactions DROP CONSTRAINT {CONSTRAINT}")
    for sql in kit.add_check(
        "leave_balance_transactions", CONSTRAINT, kit.check_in("reference_type", OLD_REFERENCES)
    ):
        op.execute(sql)
    op.execute("DROP TABLE company_transfers")

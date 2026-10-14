"""Leave quantities are exact: half days where people enter them, exact decimals in history.

docs/database-hardening-plan.md, W4.1 and decision DB-D2. Leave days were double precision,
so 12 monthly accruals of 10/12 added up to 9.9996 and a 10-day application was then refused.

- What people enter or configure is a whole or half day: days requested, encashed and granted
  as comp-off, and the entitlements and limits of leave types and bucket policies.
  numeric(6,1) with CHECK (x * 2 = trunc(x * 2)).
- History and running balances (the monthly ledger, the transaction journal, yearly balances)
  are exact decimals, numeric(9,4). Accruals from before this change keep exactly the value
  they were recorded with; from now on accrual credits whole or half days
  (leave/engine.monthly_credit), so every new movement is one too.
- Overtime rates are rates, not days: numeric(6,3).

If an entered or configured value isn't a whole or half day, the migration stops and lists
them (scripts/db_preflight.py counts them beforehand); how to round them is an HR decision.
The column type changes rewrite these tables: run in the deploy window.

Revision ID: 0060
Revises: 0059
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

# Entered or configured quantities: whole or half days.
HALF_DAYS = (
    ("leave_applications", "days_requested"),
    ("leave_encashments", "days"),
    ("comp_off_grants", "days_granted"),
    ("attendance_days", "comp_off_days"),
    ("leave_types", "days_per_year"),
    ("leave_types", "min_days_per_application"),
    ("leave_types", "max_days_per_application"),
    ("leave_types", "max_carry_forward_days"),
    ("leave_bucket_policies", "days_per_year"),
    ("leave_bucket_policies", "max_carry_forward_days"),
    ("leave_bucket_policies", "max_encashment_days"),
)
# History and running balances: exact decimals.
EXACT = (
    ("leave_balance_transactions", "quantity"),
    ("leave_balance_transactions", "previous_balance"),
    ("leave_balance_transactions", "new_balance"),
    ("leave_balances", "allocated_days"),
    ("leave_balances", "carry_forward_days"),
    ("leave_balances", "used_days"),
    ("leave_balances", "pending_days"),
    *(
        ("leave_monthly_ledger", column)
        for column in (
            "opening",
            "accrued",
            "granted",
            "held",
            "adjustment",
            "taken",
            "lapsed",
            "encashed",
            "closing",
        )
    ),
)
RATES = (("policy_templates", "ot_rate"), ("employee_policy_assignments", "ot_rate_override"))
NOT_NEGATIVE = ("allocated_days", "carry_forward_days", "used_days", "pending_days")


def upgrade() -> None:
    # Stop with a clear list, before any rewrite, if an entered value isn't a half day.
    checks = " UNION ALL ".join(
        f"SELECT '{t}.{c}' AS col, count(*) AS n FROM {t} "
        f"WHERE {c} IS NOT NULL AND abs({c} * 2 - round({c} * 2)) > 1e-9"
        for t, c in HALF_DAYS
    )
    tables = sorted({t for t, _ in HALF_DAYS})
    for table in tables:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        DO $$
        DECLARE found text;
        BEGIN
          SELECT string_agg(col || ' (' || n || ')', ', ') INTO found
          FROM ({checks}) v WHERE n > 0;
          IF found IS NOT NULL THEN
            RAISE EXCEPTION 'Leave values that are not whole or half days: %. Decide how to '
              'round them (scripts/db_preflight.py --ids), then migrate again.', found;
          END IF;
        END $$
    """)
    for table in tables:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for table, column in HALF_DAYS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE numeric(6,1) "
            f"USING round({column}::numeric, 1)"
        )
        for sql in kit.add_check(table, f"ck_{table}_{column}_half_day", kit.half_day(column)):
            op.execute(sql)
    for table, column in EXACT:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE numeric(9,4) "
            f"USING round({column}::numeric, 4)"
        )
    for table, column in RATES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE numeric(6,3) "
            f"USING round({column}::numeric, 3)"
        )
    for sql in kit.add_check(
        "leave_balances",
        "ck_leave_balances_not_negative",
        " AND ".join(f"{c} >= 0" for c in NOT_NEGATIVE),
    ):
        op.execute(sql)


def downgrade() -> None:
    op.execute("ALTER TABLE leave_balances DROP CONSTRAINT ck_leave_balances_not_negative")
    for table, column in HALF_DAYS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_{column}_half_day")
    for table, column in HALF_DAYS + EXACT + RATES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE double precision")

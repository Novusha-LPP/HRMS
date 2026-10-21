"""Room for encrypted salaries (core/field_crypto.py, "Payroll")

employee_compensations.annual_ctc becomes text so it can hold a sealed `pay:v1:...` token.
Existing amounts stay readable as plain numbers until `python -m hrms.deploy encrypt-payroll`
(run by every deploy) rewrites them under the payroll keys and pepper.

The `annual_ctc > 0` CHECK goes: the database can no longer see the number. The API still
rejects anything not above zero (schemas.py), and so does the model on write.

Revision ID: 0073
Revises: 0072
"""

import sqlalchemy as sa
from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE employee_compensations "
        "DROP CONSTRAINT IF EXISTS employee_compensations_annual_ctc_check"
    )
    op.execute(
        "ALTER TABLE employee_compensations ALTER COLUMN annual_ctc TYPE text "
        "USING annual_ctc::text"
    )
    op.execute(
        "COMMENT ON COLUMN employee_compensations.annual_ctc IS "
        "'Sealed with the payroll keys and pepper (pay:v1:...); plain only before encrypt-payroll.'"
    )


def downgrade() -> None:
    # Only possible while the amounts are plain (before encrypt-payroll, or after
    # `python -m hrms.deploy decrypt-payroll`): a sealed token is not a number.
    bind = op.get_bind()
    sealed = bind.execute(
        sa.text("SELECT count(*) FROM employee_compensations WHERE annual_ctc LIKE 'pay:v1:%'")
    ).scalar()
    if sealed:
        raise RuntimeError(
            f"{sealed} salary value(s) are encrypted: run `python -m hrms.deploy decrypt-payroll` "
            "first"
        )
    op.execute(
        "ALTER TABLE employee_compensations ALTER COLUMN annual_ctc TYPE numeric(14,2) "
        "USING annual_ctc::numeric(14,2)"
    )
    op.execute("COMMENT ON COLUMN employee_compensations.annual_ctc IS NULL")
    op.execute(
        "ALTER TABLE employee_compensations "
        "ADD CONSTRAINT employee_compensations_annual_ctc_check CHECK (annual_ctc > 0)"
    )

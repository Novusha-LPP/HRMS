"""Sign in with the employee number held on the employment, not a copy of it

login_lookup matched only user_accounts.employee_code: a copy of the employee number that
the ERP import fills in and nothing else maintains. Employees hired in HRMS have no copy,
so they couldn't sign in with their employee number at all, and any future change to a
number would leave sign-in on the old one. The lookup now also matches
employments.employee_number through the account's own employment — the one place the
number lives. employee_code stays as an alias for imported accounts.

The same number in two companies of one tenant is ambiguous like any other identifier:
up to five candidates come back and the password (or company code) settles it.

Revision ID: 0033
Revises: 0032
"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

EMPLOYMENT_NUMBER = """EXISTS (
                      SELECT 1 FROM employments e
                      WHERE e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
                        AND lower(e.employee_number) = lower(btrim(p_identifier))
                  )"""


def _v19():
    path = Path(__file__).with_name("0019_account_security_and_login_lookup.py")
    spec = importlib.util.spec_from_file_location("m0019", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _with_employment_number(sql: str) -> str:
    # 0019's union has one branch per identifier kind; add one more before the mobile ones.
    marker = "AND lower(ua.employee_code) = lower(btrim(p_identifier))"
    assert marker in sql
    branch = sql[sql.rindex("SELECT ua.tenant_id", 0, sql.index(marker)) : sql.index(marker)]
    extra = f"{branch}AND {EMPLOYMENT_NUMBER}\n                UNION ALL\n                "
    return sql.replace(branch + marker, extra + branch.lstrip() + marker, 1)


def upgrade() -> None:
    v19 = _v19()
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_employments_login_number "
        "ON employments (tenant_id, lower(employee_number))"
    )
    op.execute(_with_employment_number(v19.LOGIN_LOOKUP_V19))
    op.execute(_with_employment_number(v19.LOGIN_LOOKUP_IN_V19))


def downgrade() -> None:
    v19 = _v19()
    op.execute(v19.LOGIN_LOOKUP_V19)
    op.execute(v19.LOGIN_LOOKUP_IN_V19)
    op.execute("DROP INDEX IF EXISTS ix_employments_login_number")

"""Date ranges, sanity rules and effective dating.

docs/database-hardening-plan.md, W3.2 and W3.3; the rules are in docs/database-conventions.md.

- Range checks: effective_to is never before effective_from (an inclusive end may equal the
  start; an exclusive end may too, which is the empty row a same-day change leaves behind).
  Leave dates are ordered and days are not negative; a delegation ends after it starts; punch
  coordinates are real coordinates; fte is in (0, 1]; nobody leaves before they join.
- No overlaps where two rows at once would be a contradiction: one line manager per assignment
  at a time, and one live holiday calendar per target at a time. The app ends the old row and
  adds the new one in the same save, so these are checked at commit.
- Policy and leave-policy assignments may overlap on purpose (the latest start wins, so an
  overlapping row is a temporary override). What they may not do is start on the same day for
  the same target, where the winner would be arbitrary.

Revision ID: 0054
Revises: 0053
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

RANGE_TABLES = (
    "assignment_managers",
    "assignments",
    "employee_policy_assignments",
    "leave_policy_assignments",
    "org_units",
    "positions",
)
CHECKS = (
    ("leave_applications", "ck_leave_applications_dates", "to_date >= from_date"),
    ("leave_applications", "ck_leave_applications_days", "days_requested >= 0"),
    ("approval_delegations", "ck_approval_delegations_period", "valid_until > valid_from"),
    (
        "punches",
        "ck_punches_coordinates",
        "(latitude IS NULL OR latitude BETWEEN -90 AND 90) "
        "AND (longitude IS NULL OR longitude BETWEEN -180 AND 180)",
    ),
    ("assignments", "ck_assignments_fte", "fte > 0 AND fte <= 1"),
    (
        "employments",
        "ck_employments_separation",
        "separation_date IS NULL OR separation_date >= hire_date",
    ),
)
LIVE = "archived_at IS NULL"
CALENDAR_SCOPES = {
    "ex_hca_employment": (["employment_id"], f"employment_id IS NOT NULL AND {LIVE}"),
    "ex_hca_org_unit": (["org_unit_id"], f"org_unit_id IS NOT NULL AND {LIVE}"),
    "ex_hca_legal_entity": (["legal_entity_id"], f"legal_entity_id IS NOT NULL AND {LIVE}"),
    "ex_hca_tenant_default": (
        [],
        f"employment_id IS NULL AND org_unit_id IS NULL AND legal_entity_id IS NULL AND {LIVE}",
    ),
}
SAME_START = [
    (f"uq_{short}_same_start_{scope.removesuffix('_id')}", table, scope)
    for short, table in (
        ("epa", "employee_policy_assignments"),
        ("lpa", "leave_policy_assignments"),
    )
    for scope in ("employment_id", "org_unit_id", "legal_entity_id")
]


def upgrade() -> None:
    for table in RANGE_TABLES:
        for sql in kit.effective_range_check(table):
            op.execute(sql)
    for table, name, expression in CHECKS:
        for sql in kit.add_check(table, name, expression):
            op.execute(sql)
    op.execute(
        kit.no_overlap(
            "assignment_managers",
            "ex_assignment_managers_period",
            ["assignment_id", "manager_type"],
            end_inclusive=False,
            deferred=True,
        )
    )
    for name, (keys, where) in CALENDAR_SCOPES.items():
        op.execute(
            kit.no_overlap(
                "holiday_calendar_assignments",
                name,
                keys,
                end_inclusive=True,
                where=where,
                deferred=True,
            )
        )
    for name, table, scope in SAME_START:
        op.execute(
            kit.index(
                table,
                ["tenant_id", scope, "effective_from"],
                name=name,
                unique=True,
                where=f"{scope} IS NOT NULL AND {LIVE}",
            )
        )


def downgrade() -> None:
    for name, _, _ in SAME_START:
        op.execute(f"DROP INDEX {name}")
    for name in CALENDAR_SCOPES:
        op.execute(f"ALTER TABLE holiday_calendar_assignments DROP CONSTRAINT {name}")
    op.execute("ALTER TABLE assignment_managers DROP CONSTRAINT ex_assignment_managers_period")
    for table, name, _ in CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    for table in RANGE_TABLES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_effective_range")

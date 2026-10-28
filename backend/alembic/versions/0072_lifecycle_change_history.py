"""Change history for the leavers and rejoining settings and records.

docs/REJOIN_DEVELOPMENT_PLAN.md, R9. Who added or removed a leave rule for leavers, a rejoin
policy or a period of earlier service, and who moved someone between companies, is recorded by
a trigger (the same one migration 0062 uses), so every write path is covered.

Revision ID: 0072
Revises: 0071
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

AUDITED = {
    "leave_separation_rules": "leave_separation_rule",
    "rejoin_policies": "rejoin_policy",
    "prior_service": "prior_service",
    "company_transfers": "company_transfer",
}


def upgrade() -> None:
    for table, entity_type in AUDITED.items():
        op.execute(kit.record_changes(table, entity_type))


def downgrade() -> None:
    for table in AUDITED:
        op.execute(f"DROP TRIGGER IF EXISTS record_{table}_change ON {table}")

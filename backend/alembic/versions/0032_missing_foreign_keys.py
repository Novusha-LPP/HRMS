"""Foreign keys that were missing: org unit location / cost centre, onboarding template item

org_units.location_id, org_units.cost_centre_id and onboarding_items.template_item_id named
rows in other tables with nothing making sure those rows exist, or belong to the same
company. Like every other reference here they become composite (tenant_id, id) keys,
deferrable to the end of the transaction.

Added NOT VALID and then validated, so existing rows are checked without blocking writes
to the tables while it runs. (Checked on the testing database before writing this: no row
points at a missing location, cost centre or template item.)

Revision ID: 0032
Revises: 0031
"""

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

FOREIGN_KEYS = [
    ("org_units", "location_id", "locations"),
    ("org_units", "cost_centre_id", "cost_centres"),
    ("onboarding_items", "template_item_id", "onboarding_template_items"),
]


def upgrade() -> None:
    for table, column, target in FOREIGN_KEYS:
        name = f"fk_{table}_{column}"
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, {column}) "
            f"REFERENCES {target} (tenant_id, id) DEFERRABLE INITIALLY DEFERRED NOT VALID"
        )
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    for table, column, _ in FOREIGN_KEYS:
        op.drop_constraint(f"fk_{table}_{column}", table, type_="foreignkey")

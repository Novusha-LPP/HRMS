"""Legal-entity (company-wide) policy assignment.

Department assignment (0012) relies on org_unit_id, which requires the
tenant to have built out an org_unit tree and the employee to have a
current Assignment row — neither is guaranteed for a brand-new tenant
(tenant_provisioning.py creates a legal entity but no org_unit at all).
legal_entity_id is set on every employment at hire regardless, so this is
the tier that reliably means "the whole company."

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employee_policy_assignments",
        sa.Column("legal_entity_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_epa_legal_entity", "employee_policy_assignments", ["legal_entity_id"])

    op.drop_constraint("ck_epa_exactly_one_target", "employee_policy_assignments", type_="check")
    op.create_check_constraint(
        "ck_epa_exactly_one_target",
        "employee_policy_assignments",
        "num_nonnulls(employment_id, org_unit_id, legal_entity_id) = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_epa_exactly_one_target", "employee_policy_assignments", type_="check")
    op.create_check_constraint(
        "ck_epa_exactly_one_target",
        "employee_policy_assignments",
        "(employment_id IS NOT NULL) != (org_unit_id IS NOT NULL)",
    )
    op.drop_index("ix_epa_legal_entity", table_name="employee_policy_assignments")
    op.drop_column("employee_policy_assignments", "legal_entity_id")

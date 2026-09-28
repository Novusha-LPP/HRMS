"""Record which login acted on a leave/correction approval.

Approvals were stamped only with the approver's employment, so a company
administrator whose login has no employee record could not approve anything
(the API refused with "no employment record"). The account that acted is now
stored too; approver_employment_id stays for people who do have an employment.

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TABLES = ("leave_approval_actions", "correction_approval_actions")


def upgrade() -> None:
    for t in TABLES:
        op.add_column(t, sa.Column("approver_user_account_id", UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    for t in TABLES:
        op.drop_column(t, "approver_user_account_id")

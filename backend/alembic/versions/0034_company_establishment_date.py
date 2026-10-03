"""Company establishment date for anniversary celebrations."""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("legal_entities", sa.Column("establishment_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("legal_entities", "establishment_date")

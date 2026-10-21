"""Service with an earlier employer, recorded when someone is hired.

docs/REJOIN_DEVELOPMENT_PLAN.md, R6. Expand only: one new tenant table. A period of work for
another employer can be recognised for leave eligibility, for gratuity, both or neither. It
belongs to the person, so it follows them across employments.

Revision ID: 0070
Revises: 0069
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for sql in kit.tenant_table(
        "prior_service",
        """
        person_id uuid NOT NULL,
        employer_name varchar(200) NOT NULL,
        from_date date NOT NULL,
        to_date date NOT NULL,
        recognised_for_leave boolean NOT NULL DEFAULT false,
        recognised_for_gratuity boolean NOT NULL DEFAULT false,
        note varchar(500),
        document_id uuid,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_prior_service_dates CHECK (to_date >= from_date)
        """,
        comment=(
            "A period of work for an earlier employer that this company recognises for leave "
            "eligibility, gratuity, both or neither. Belongs to the person, not one employment."
        ),
        references={
            "person_id": "persons",
            "document_id": "employee_kyc_documents",
            "created_by": "user_accounts",
        },
    ):
        op.execute(sql)


def downgrade() -> None:
    op.execute("DROP TABLE prior_service")

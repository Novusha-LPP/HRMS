"""Room for encrypted identifiers (core/field_crypto.py)

Aadhaar, PAN, UAN, PF, ESI, passport, driving licence, voter ID and bank account numbers
(employee_kyc_records), and the number printed on an uploaded document
(employee_kyc_documents.document_number), are now stored as AES-256-GCM tokens, which are
longer than the plain values: the columns become text. Lengths are checked by the API
schemas instead.

This migration only changes types. Existing plain values keep working (they are read
as-is) until `python -m hrms.deploy encrypt-pii` rewrites them encrypted.

Revision ID: 0030
Revises: 0029
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

RECORD_COLUMNS = {
    "pan_number": 20,
    "aadhaar_number": 20,
    "uan_number": 20,
    "pf_number": 50,
    "esi_number": 50,
    "passport_number": 50,
    "driving_license": 50,
    "voter_id": 50,
    "account_number": 50,
}


def upgrade() -> None:
    for column in RECORD_COLUMNS:
        op.alter_column("employee_kyc_records", column, type_=sa.Text())
    op.alter_column("employee_kyc_documents", "document_number", type_=sa.Text())


def downgrade() -> None:
    # Only possible while the values are still plain (before encrypt-pii, or after
    # `python -m hrms.deploy decrypt-pii`): an encrypted token doesn't fit the old lengths.
    for column, length in RECORD_COLUMNS.items():
        op.alter_column("employee_kyc_records", column, type_=sa.String(length))
    op.alter_column("employee_kyc_documents", "document_number", type_=sa.String(100))

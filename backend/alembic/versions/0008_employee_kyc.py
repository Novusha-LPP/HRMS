"""Employee KYC records and documents

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"


def upgrade() -> None:
    # ── KYC Records ────────────────────────────────────────────────────────────
    op.create_table(
        "employee_kyc_records",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", UUID(as_uuid=True), nullable=True),
        # Identity
        sa.Column("pan_number", sa.String(20)),
        sa.Column("aadhaar_number", sa.String(20)),
        sa.Column("uan_number", sa.String(20)),
        sa.Column("pf_number", sa.String(50)),
        sa.Column("esi_number", sa.String(50)),
        sa.Column("passport_number", sa.String(50)),
        sa.Column("passport_expiry", sa.Date),
        sa.Column("driving_license", sa.String(50)),
        sa.Column("voter_id", sa.String(50)),
        # Bank
        sa.Column("bank_name", sa.String(100)),
        sa.Column("account_holder_name", sa.String(255)),
        sa.Column("account_number", sa.String(50)),
        sa.Column("ifsc_code", sa.String(20)),
        sa.Column("branch_name", sa.String(100)),
        # Personal & Family
        sa.Column("father_or_spouse_name", sa.String(255)),
        sa.Column("marital_status", sa.String(20)),
        sa.Column("blood_group", sa.String(10)),
        sa.Column("emergency_contact_name", sa.String(255)),
        sa.Column("emergency_contact_relation", sa.String(50)),
        sa.Column("emergency_contact_phone", sa.String(20)),
        sa.Column("current_address", sa.String(500)),
        sa.Column("permanent_address", sa.String(500)),
        # Status & Verification
        sa.Column("status", sa.String(50), nullable=False, server_default="NOT_SUBMITTED"),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("verified_by", UUID(as_uuid=True)),
        sa.Column("rejection_reason", sa.String(1000)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_by", UUID(as_uuid=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint("tenant_id", "employment_id", name="uq_tenant_kyc_employment"),
    )
    op.create_index(
        "ix_employee_kyc_records_emp", "employee_kyc_records", ["tenant_id", "employment_id"]
    )
    _enable_rls("employee_kyc_records")

    # ── KYC Documents ──────────────────────────────────────────────────────────
    op.create_table(
        "employee_kyc_documents",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("employment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("document_title", sa.String(255), nullable=False),
        sa.Column("document_number", sa.String(100)),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("rejection_reason", sa.String(1000)),
        sa.Column("comments", sa.String(1000)),
        sa.Column("uploaded_by", UUID(as_uuid=True)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("verified_by", UUID(as_uuid=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index(
        "ix_employee_kyc_documents_emp", "employee_kyc_documents", ["tenant_id", "employment_id"]
    )
    _enable_rls("employee_kyc_documents")

    # Grant permissions to APP_ROLE
    for table in ("employee_kyc_records", "employee_kyc_documents"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (tenant_id = current_tenant_id())
        WITH CHECK (tenant_id = current_tenant_id())
    """)


def downgrade() -> None:
    for t in ["employee_kyc_documents", "employee_kyc_records"]:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

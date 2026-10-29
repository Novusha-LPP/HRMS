"""Payslip branding: company details, logos, signatories and the payslip layout.

HR and Admin set how payslips (and later letters) look, once for the group and per company
where a company differs. Expand only:

- legal_entities gains the company details a payslip prints: registered name and address,
  CIN, PAN, TAN, GSTIN, PF establishment code and ESIC employer code;
- brand_assets: uploaded logos and signature images, re-encoded to PNG, immutable (a payslip
  issued with a logo keeps pointing at it);
- brand_profiles: logo, colours, footer and contact details. legal_entity_id NULL is the
  group default; a company's row overrides only the fields it sets (NULL = inherit);
- document_signatories: who signs documents, optionally for one company only;
- payslip_templates: the layout and what a payslip shows. legal_entity_id NULL is the group
  default; a company either uses it or has its own complete template.

Revision ID: 0075
Revises: 0074
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None

COMPANY_DETAILS = (
    ("registered_name", "varchar(255)"),
    ("address_line1", "varchar(255)"),
    ("address_line2", "varchar(255)"),
    ("city", "varchar(100)"),
    ("state_code", "varchar(10)"),
    ("pincode", "varchar(10)"),
    ("cin", "varchar(21)"),
    ("pan", "varchar(10)"),
    ("tan", "varchar(10)"),
    ("gstin", "varchar(15)"),
    ("pf_establishment_code", "varchar(22)"),
    ("esic_employer_code", "varchar(17)"),
)
COLOR = "^#[0-9A-F]{6}$"


def _one_per_scope(table: str) -> str:
    # One row per company and one group row (NULL company): NULLS NOT DISTINCT makes the NULL
    # count as a value. The same index serves the legal_entity_id foreign key.
    return (
        f"CREATE UNIQUE INDEX uq_{table}_scope ON {table} (tenant_id, legal_entity_id) "
        "NULLS NOT DISTINCT"
    )


def upgrade() -> None:
    for column, sql_type in COMPANY_DETAILS:
        op.execute(f"ALTER TABLE legal_entities ADD COLUMN {column} {sql_type}")

    for sql in kit.tenant_table(
        "brand_assets",
        f"""
        kind varchar(20) NOT NULL,
        file_name varchar(255) NOT NULL,
        width integer NOT NULL,
        height integer NOT NULL,
        byte_size integer NOT NULL,
        sha256 char(64) NOT NULL,
        storage_ref varchar(500) NOT NULL,
        uploaded_by uuid,
        uploaded_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_brand_assets_kind CHECK ({kit.check_in("kind", ("LOGO", "SIGNATURE"))}),
        CONSTRAINT ck_brand_assets_size CHECK (width > 0 AND height > 0 AND byte_size > 0)
        """,
        comment=(
            "Logos and signature images uploaded for documents, re-encoded to PNG. Never "
            "changed or removed, so a payslip issued with an image can always be reproduced."
        ),
        references={"uploaded_by": "user_accounts"},
        append_only=True,
    ):
        op.execute(sql)

    for sql in kit.tenant_table(
        "brand_profiles",
        f"""
        legal_entity_id uuid,
        logo_asset_id uuid,
        primary_color varchar(7),
        accent_color varchar(7),
        footer_text varchar(500),
        contact_email varchar(320),
        contact_phone varchar(30),
        website varchar(255),
        recorded_by uuid,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        CONSTRAINT ck_brand_profiles_colors CHECK (
            (primary_color IS NULL OR primary_color ~ '{COLOR}')
            AND (accent_color IS NULL OR accent_color ~ '{COLOR}')),
        {kit.tenant_fk("brand_profiles", "legal_entity_id", "legal_entities")}
        """,
        comment=(
            "How documents look: logo, colours, footer and contact details. The row without a "
            "company is the group default; a company row overrides only the fields it sets."
        ),
        # legal_entity_id's key is inline above: uq_brand_profiles_scope serves it.
        references={"logo_asset_id": "brand_assets", "recorded_by": "user_accounts"},
    ):
        op.execute(sql)
    op.execute(_one_per_scope("brand_profiles"))
    op.execute(kit.record_changes("brand_profiles", "brand_profile"))

    for sql in kit.tenant_table(
        "document_signatories",
        """
        legal_entity_id uuid,
        name varchar(120) NOT NULL,
        designation varchar(120),
        signature_asset_id uuid,
        recorded_by uuid,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        archived_at timestamptz
        """,
        comment=(
            "People who sign documents (payslips, later letters): name, designation and an "
            "optional signature image; for one company, or for any company when none is set."
        ),
        references={
            "legal_entity_id": "legal_entities",
            "signature_asset_id": "brand_assets",
            "recorded_by": "user_accounts",
        },
    ):
        op.execute(sql)
    op.execute(kit.record_changes("document_signatories", "document_signatory"))

    for sql in kit.tenant_table(
        "payslip_templates",
        f"""
        legal_entity_id uuid,
        layout varchar(20) NOT NULL DEFAULT 'MODERN',
        title varchar(60) NOT NULL DEFAULT 'Payslip',
        employee_fields jsonb NOT NULL DEFAULT '[]'::jsonb,
        show_attendance boolean NOT NULL DEFAULT true,
        show_leave_balances boolean NOT NULL DEFAULT false,
        show_employer_contributions boolean NOT NULL DEFAULT false,
        show_ytd boolean NOT NULL DEFAULT false,
        hide_zero_lines boolean NOT NULL DEFAULT true,
        signature_mode varchar(20) NOT NULL DEFAULT 'COMPUTER_GENERATED',
        signatory_id uuid,
        note_text varchar(500),
        recorded_by uuid,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        CONSTRAINT ck_payslip_templates_layout
            CHECK ({kit.check_in("layout", ("MODERN", "CLASSIC", "COMPACT"))}),
        CONSTRAINT ck_payslip_templates_signature_mode
            CHECK ({kit.check_in("signature_mode", ("COMPUTER_GENERATED", "SIGNATORY"))}),
        CONSTRAINT ck_payslip_templates_signatory
            CHECK (signature_mode <> 'SIGNATORY' OR signatory_id IS NOT NULL),
        {kit.tenant_fk("payslip_templates", "legal_entity_id", "legal_entities")}
        """,
        comment=(
            "What a payslip shows and in which layout. The row without a company is the group "
            "default; a company with its own row uses that instead, as a whole."
        ),
        # legal_entity_id's key is inline above: uq_payslip_templates_scope serves it.
        references={"signatory_id": "document_signatories", "recorded_by": "user_accounts"},
    ):
        op.execute(sql)
    op.execute(_one_per_scope("payslip_templates"))
    op.execute(kit.record_changes("payslip_templates", "payslip_template"))


def downgrade() -> None:
    filled = " OR ".join(f"{column} IS NOT NULL" for column, _ in COMPANY_DETAILS)
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM brand_assets) OR EXISTS (SELECT 1 FROM brand_profiles)
             OR EXISTS (SELECT 1 FROM document_signatories)
             OR EXISTS (SELECT 1 FROM payslip_templates)
             OR EXISTS (SELECT 1 FROM legal_entities WHERE {filled}) THEN
            RAISE EXCEPTION 'payslip branding is set up; it cannot be rolled back';
          END IF;
        END $$
        """
    )
    for table in ("payslip_templates", "document_signatories", "brand_profiles", "brand_assets"):
        op.execute(f"DROP TABLE {table}")
    for column, _ in COMPANY_DETAILS:
        op.execute(f"ALTER TABLE legal_entities DROP COLUMN {column}")

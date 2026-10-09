"""Payroll foundation: payroll roles, statutory rule values, pay components, salary
structures (versioned) and employee compensation (effective-dated, no overlaps).

Amounts are plain numerics, not encrypted: payroll has to add and compare them in SQL.
They are protected by row-level security, by the payroll.* permissions (which HR_MANAGER
does not hold) and by company scope.
"""

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

TABLES = (
    "statutory_rules",
    "pay_components",
    "salary_structures",
    "salary_structure_lines",
    "employee_compensations",
)

NEW_ROLES = {
    "PAYROLL_ADMIN": "Maintain salary structures and employee salaries, and run payroll",
    "PAYROLL_APPROVER": "Approve and lock pay runs prepared by the payroll administrator",
    "PAYROLL_REVIEWER": "Check statutory values and payroll calculations, and sign them off",
}


def _fk(table, column, target, on_delete=""):
    return (
        f"CONSTRAINT fk_{table}_{column} FOREIGN KEY (tenant_id, {column}) "
        f"REFERENCES {target}(tenant_id, id) {on_delete} DEFERRABLE INITIALLY DEFERRED"
    )


def upgrade():
    # Existing companies get the new system roles; new ones get them at registration.
    op.execute("ALTER TABLE roles NO FORCE ROW LEVEL SECURITY")
    for name, description in NEW_ROLES.items():
        op.execute(f"""
            INSERT INTO roles (tenant_id, id, name, description, is_system, version)
            SELECT t.id, gen_random_uuid(), '{name}', '{description}', true, 0
            FROM tenants t
            WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.name = '{name}')
        """)
    # Check the deferred foreign keys now: a table with pending trigger events can't be altered.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("ALTER TABLE roles FORCE ROW LEVEL SECURITY")

    op.execute(f"""CREATE TABLE statutory_rules (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        country_code varchar(2) NOT NULL DEFAULT 'IN',
        rule_code varchar(60) NOT NULL,
        state_code varchar(10),
        value numeric(14,4) NOT NULL,
        unit varchar(10) NOT NULL CHECK (unit IN ('PERCENT','AMOUNT','FLAG')),
        effective_from date NOT NULL,
        effective_to date,
        source text NOT NULL,
        verified_by uuid,
        verified_at timestamptz,
        status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','RETIRED')),
        recorded_by uuid,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, id),
        CHECK (effective_to IS NULL OR effective_to > effective_from),
        {_fk("statutory_rules", "verified_by", "user_accounts")},
        {_fk("statutory_rules", "recorded_by", "user_accounts")}
    )""")
    op.execute("""
        ALTER TABLE statutory_rules ADD CONSTRAINT uq_statutory_rule_no_overlap
        EXCLUDE USING GIST (
            tenant_id WITH =,
            rule_code WITH =,
            (COALESCE(state_code, '')) WITH =,
            daterange(effective_from, COALESCE(effective_to, '9999-12-31'::date), '[)') WITH &&
        ) WHERE (status = 'ACTIVE')
    """)

    op.execute(f"""CREATE TABLE pay_components (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        code varchar(30) NOT NULL,
        name varchar(100) NOT NULL,
        kind varchar(30) NOT NULL CHECK (kind IN
            ('EARNING','DEDUCTION','EMPLOYER_CONTRIBUTION','REIMBURSEMENT','INFO')),
        statutory_code varchar(30) CHECK (statutory_code IN
            ('PF_EMPLOYEE','PF_EMPLOYER','ESIC_EMPLOYEE','ESIC_EMPLOYER')),
        taxable boolean NOT NULL DEFAULT true,
        in_pf_wages boolean NOT NULL DEFAULT false,
        in_esic_wages boolean NOT NULL DEFAULT true,
        prorate boolean NOT NULL DEFAULT true,
        payslip_order integer NOT NULL DEFAULT 0,
        status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
        recorded_by uuid,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        archived_at timestamptz,
        PRIMARY KEY (tenant_id, id),
        {_fk("pay_components", "recorded_by", "user_accounts")}
    )""")
    op.execute(
        "CREATE UNIQUE INDEX uq_pay_component_code ON pay_components (tenant_id, lower(code)) "
        "WHERE archived_at IS NULL"
    )

    op.execute(f"""CREATE TABLE salary_structures (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        name varchar(120) NOT NULL,
        description varchar(500),
        legal_entity_id uuid,
        status varchar(20) NOT NULL DEFAULT 'ACTIVE'
            CHECK (status IN ('ACTIVE','RETIRED','INACTIVE')),
        supersedes_id uuid,
        recorded_by uuid,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, id),
        {_fk("salary_structures", "legal_entity_id", "legal_entities")},
        {_fk("salary_structures", "supersedes_id", "salary_structures")},
        {_fk("salary_structures", "recorded_by", "user_accounts")}
    )""")

    op.execute(f"""CREATE TABLE salary_structure_lines (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        structure_id uuid NOT NULL,
        component_id uuid NOT NULL,
        sequence integer NOT NULL DEFAULT 0,
        calc_type varchar(20) NOT NULL CHECK (calc_type IN
            ('FIXED','PERCENT','BALANCE','STATUTORY')),
        amount numeric(14,2) CHECK (amount >= 0),
        percent numeric(7,4) CHECK (percent >= 0 AND percent <= 100),
        base varchar(20) CHECK (base IN ('CTC','COMPONENT')),
        base_component_id uuid,
        min_amount numeric(14,2) CHECK (min_amount >= 0),
        max_amount numeric(14,2) CHECK (max_amount >= 0),
        PRIMARY KEY (tenant_id, id),
        {_fk("salary_structure_lines", "structure_id", "salary_structures", "ON DELETE CASCADE")},
        {_fk("salary_structure_lines", "component_id", "pay_components")},
        {_fk("salary_structure_lines", "base_component_id", "pay_components")}
    )""")
    op.execute(
        "CREATE INDEX ix_salary_structure_lines_structure "
        "ON salary_structure_lines (tenant_id, structure_id, sequence)"
    )

    op.execute(f"""CREATE TABLE employee_compensations (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        employment_id uuid NOT NULL,
        structure_id uuid NOT NULL,
        annual_ctc numeric(14,2) NOT NULL CHECK (annual_ctc > 0),
        currency varchar(3) NOT NULL DEFAULT 'INR',
        effective_from date NOT NULL,
        effective_to date,
        reason varchar(100),
        note varchar(500),
        recorded_by uuid,
        recorded_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, id),
        CHECK (effective_to IS NULL OR effective_to > effective_from),
        {_fk("employee_compensations", "employment_id", "employments")},
        {_fk("employee_compensations", "structure_id", "salary_structures")},
        {_fk("employee_compensations", "recorded_by", "user_accounts")}
    )""")
    op.execute("""
        ALTER TABLE employee_compensations ADD CONSTRAINT uq_compensation_no_overlap
        EXCLUDE USING GIST (
            tenant_id WITH =,
            employment_id WITH =,
            daterange(effective_from, COALESCE(effective_to, '9999-12-31'::date), '[)') WITH &&
        )
    """)
    op.execute(
        "CREATE INDEX ix_employee_compensations_employment "
        "ON employee_compensations (tenant_id, employment_id, effective_from)"
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            "(tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id())"
        )


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE roles NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_assignments NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM role_assignments WHERE role_id IN (SELECT id FROM roles WHERE name IN "
        "('PAYROLL_ADMIN','PAYROLL_APPROVER','PAYROLL_REVIEWER'))"
    )
    op.execute(
        "DELETE FROM roles WHERE name IN ('PAYROLL_ADMIN','PAYROLL_APPROVER','PAYROLL_REVIEWER')"
    )
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute("ALTER TABLE role_assignments FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE roles FORCE ROW LEVEL SECURITY")

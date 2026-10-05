"""Recruitment: job openings, a configurable candidate pipeline, candidates and history."""

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

TABLES = (
    "recruitment_stages",
    "job_openings",
    "candidates",
    "job_applications",
    "recruitment_events",
)


def _fk(table, column, target, on_delete=""):
    return (
        f"CONSTRAINT fk_{table}_{column} FOREIGN KEY (tenant_id, {column}) "
        f"REFERENCES {target}(tenant_id, id) {on_delete} DEFERRABLE INITIALLY DEFERRED"
    )


def upgrade():
    op.execute("""CREATE TABLE recruitment_stages (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        name varchar(60) NOT NULL,
        category varchar(20) NOT NULL DEFAULT 'ACTIVE'
            CHECK (category IN ('ACTIVE','HIRED','REJECTED','WITHDRAWN')),
        color varchar(20) NOT NULL DEFAULT 'neutral',
        sequence integer NOT NULL DEFAULT 0,
        is_active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 1,
        PRIMARY KEY (tenant_id, id)
    )""")
    op.execute(
        "CREATE UNIQUE INDEX uq_recruitment_stage_name "
        "ON recruitment_stages (tenant_id, lower(name))"
    )

    op.execute(f"""CREATE TABLE job_openings (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        code varchar(20) NOT NULL,
        title varchar(150) NOT NULL,
        legal_entity_id uuid NOT NULL,
        org_unit_id uuid NOT NULL,
        job_id uuid,
        location_id uuid,
        hiring_manager_employment_id uuid,
        requested_by uuid NOT NULL,
        requester_employment_id uuid,
        employment_type varchar(20) NOT NULL
            CHECK (employment_type IN ('FULL_TIME','PART_TIME','CONTRACT','INTERN','CONSULTANT')),
        work_mode varchar(20) NOT NULL CHECK (work_mode IN ('ONSITE','HYBRID','REMOTE')),
        positions integer NOT NULL DEFAULT 1 CHECK (positions BETWEEN 1 AND 500),
        priority varchar(20) NOT NULL CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
        reason varchar(20) NOT NULL CHECK (reason IN ('NEW_ROLE','REPLACEMENT','EXPANSION')),
        replacement_for varchar(150),
        min_experience_years numeric(4,1) CHECK (min_experience_years >= 0),
        max_experience_years numeric(4,1),
        salary_min numeric(14,2) CHECK (salary_min >= 0),
        salary_max numeric(14,2),
        currency varchar(3) NOT NULL DEFAULT 'INR',
        target_start_date date,
        description text NOT NULL,
        responsibilities text,
        requirements text,
        skills jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(skills) = 'array'),
        status varchar(20) NOT NULL DEFAULT 'DRAFT' CHECK (status IN
            ('DRAFT','PENDING_APPROVAL','REJECTED','OPEN','ON_HOLD','FILLED','CLOSED')),
        approval_mode varchar(10) CHECK (approval_mode IN ('FLOW','HR','AUTO')),
        submitted_at timestamptz,
        approved_at timestamptz,
        approved_by uuid,
        decision_comment varchar(1000),
        closed_at timestamptz,
        close_reason varchar(500),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 1,
        PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_opening_experience CHECK (
            max_experience_years IS NULL OR min_experience_years IS NULL
            OR max_experience_years >= min_experience_years),
        CONSTRAINT ck_opening_salary CHECK (
            salary_max IS NULL OR salary_min IS NULL OR salary_max >= salary_min),
        {_fk("job_openings", "legal_entity_id", "legal_entities")},
        {_fk("job_openings", "org_unit_id", "org_units")},
        {_fk("job_openings", "job_id", "jobs")},
        {_fk("job_openings", "location_id", "locations")},
        {_fk("job_openings", "hiring_manager_employment_id", "employments")},
        {_fk("job_openings", "requested_by", "user_accounts")},
        {_fk("job_openings", "requester_employment_id", "employments")},
        {_fk("job_openings", "approved_by", "user_accounts")}
    )""")
    op.execute("CREATE UNIQUE INDEX uq_job_opening_code ON job_openings (tenant_id, code)")
    op.execute("CREATE INDEX ix_job_openings_status ON job_openings (tenant_id, status)")
    op.execute("CREATE INDEX ix_job_openings_unit ON job_openings (tenant_id, org_unit_id)")

    op.execute(f"""CREATE TABLE candidates (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        first_name varchar(100) NOT NULL,
        last_name varchar(100) NOT NULL,
        email varchar(320),
        phone varchar(30),
        location varchar(120),
        current_company varchar(150),
        current_title varchar(150),
        total_experience_years numeric(4,1) CHECK (total_experience_years >= 0),
        current_ctc numeric(14,2) CHECK (current_ctc >= 0),
        expected_ctc numeric(14,2) CHECK (expected_ctc >= 0),
        notice_period_days integer CHECK (notice_period_days BETWEEN 0 AND 365),
        source varchar(30) NOT NULL,
        source_detail varchar(150),
        links jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(links) = 'array'),
        skills jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(skills) = 'array'),
        summary text,
        resume_ref varchar(500),
        resume_file_name varchar(150),
        resume_mime_type varchar(100),
        resume_size integer,
        resume_uploaded_at timestamptz,
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 1,
        PRIMARY KEY (tenant_id, id),
        {_fk("candidates", "created_by", "user_accounts")}
    )""")
    # One talent-pool record per address: a second application reuses the candidate.
    op.execute(
        "CREATE UNIQUE INDEX uq_candidate_email ON candidates (tenant_id, lower(email)) "
        "WHERE email IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_candidates_created ON candidates (tenant_id, created_at DESC)")

    op.execute(f"""CREATE TABLE job_applications (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        opening_id uuid NOT NULL,
        candidate_id uuid NOT NULL,
        stage_id uuid NOT NULL,
        rating smallint CHECK (rating BETWEEN 1 AND 5),
        owner_user_id uuid,
        hired_employment_id uuid,
        outcome_reason varchar(500),
        applied_at timestamptz NOT NULL DEFAULT now(),
        stage_changed_at timestamptz NOT NULL DEFAULT now(),
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 1,
        PRIMARY KEY (tenant_id, id),
        {_fk("job_applications", "opening_id", "job_openings", "ON DELETE CASCADE")},
        {_fk("job_applications", "candidate_id", "candidates", "ON DELETE CASCADE")},
        {_fk("job_applications", "stage_id", "recruitment_stages")},
        {_fk("job_applications", "owner_user_id", "user_accounts")},
        {_fk("job_applications", "hired_employment_id", "employments")},
        {_fk("job_applications", "created_by", "user_accounts")}
    )""")
    op.execute(
        "CREATE UNIQUE INDEX uq_application_candidate "
        "ON job_applications (tenant_id, opening_id, candidate_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_application_hired_employment "
        "ON job_applications (tenant_id, hired_employment_id) WHERE hired_employment_id IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_applications_stage ON job_applications (tenant_id, stage_id)")
    op.execute(
        "CREATE INDEX ix_applications_candidate ON job_applications (tenant_id, candidate_id)"
    )

    op.execute(f"""CREATE TABLE recruitment_events (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        id uuid NOT NULL,
        opening_id uuid NOT NULL,
        application_id uuid,
        actor_user_id uuid,
        action varchar(30) NOT NULL,
        details jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, id),
        {_fk("recruitment_events", "opening_id", "job_openings", "ON DELETE CASCADE")},
        {_fk("recruitment_events", "application_id", "job_applications", "ON DELETE CASCADE")},
        {_fk("recruitment_events", "actor_user_id", "user_accounts")}
    )""")
    op.execute(
        "CREATE INDEX ix_recruitment_events_opening "
        "ON recruitment_events (tenant_id, opening_id, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_recruitment_events_application "
        "ON recruitment_events (tenant_id, application_id, created_at)"
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

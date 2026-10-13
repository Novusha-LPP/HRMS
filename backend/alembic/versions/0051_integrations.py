"""Integrations: connected apps, API keys, employee sync, settings and the events feed.

docs/erp-crm-integration-plan.md is the design. In short:

- connected_apps: each outside system (an ERP, a CRM, a BI tool) a tenant connects.
- api_keys (from 0018) now belong to an app, carry an environment (test/live) and can be
  revoked. They are found by hash through integration_key_lookup(), a SECURITY DEFINER
  function, because no tenant context exists when a key arrives (the same reason as
  login_lookup()).
- external_identities: one row per (app, employee). An employee can be in the ERP and the CRM
  under different IDs, which user_accounts.erp_system/erp_user_id (one pair) could not hold.
  Existing pairs are copied over; the old columns stay until a later contract migration.
- integration_mappings: an app's value ("Ops") -> an HRMS company, department, location,
  designation or role.
- integration_profiles: versioned settings per app, as a tenant default or a company override.
  A published version is never edited; a change is a new version.
- integration_requests: the sync log. Append-only for the app role, except that the retention
  job may delete old rows.
- integration_events + integration_app_events: the outbox and its per-app fan-out. An app's
  feed position (seq) is assigned when an event becomes available to that app, and the feed
  only returns rows whose assigning transaction is older than every transaction still running,
  so a slow commit can never be skipped.
- possible_duplicates: records an app sent that look like an unlinked HRMS employee.
- integration_rate_windows: per-key, per-minute request counters.
- punches.source_system: which app recorded a punch made through an employee session.
"""

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

APP_ROLE = "hrms_app"

TENANT_TABLES = (
    "connected_apps",
    "external_identities",
    "integration_mappings",
    "integration_profiles",
    "integration_requests",
    "integration_events",
    "integration_app_events",
    "integration_cursors",
    "possible_duplicates",
    "integration_rate_windows",
)


def _fk(table, column, target, on_delete=""):
    return (
        f"CONSTRAINT fk_{table}_{column} FOREIGN KEY (tenant_id, {column}) "
        f"REFERENCES {target}(tenant_id, id) {on_delete} DEFERRABLE INITIALLY DEFERRED"
    )


def upgrade():
    op.execute("""
        CREATE TABLE connected_apps (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id uuid NOT NULL,
            code varchar(40) NOT NULL,
            name varchar(120) NOT NULL,
            kind varchar(20) NOT NULL,
            status varchar(20) NOT NULL DEFAULT 'ACTIVE',
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            paused_at timestamptz,
            disconnected_at timestamptz,
            PRIMARY KEY (tenant_id, id),
            CONSTRAINT ck_connected_apps_kind
                CHECK (kind IN ('TWO_WAY', 'RECEIVE_ONLY', 'READ_ONLY')),
            CONSTRAINT ck_connected_apps_status
                CHECK (status IN ('ACTIVE', 'PAUSED', 'DISCONNECTED')),
            CONSTRAINT ck_connected_apps_code CHECK (code ~ '^[A-Z][A-Z0-9_]{1,39}$')
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX uq_connected_apps_code ON connected_apps (tenant_id, code) "
        "WHERE status <> 'DISCONNECTED'"
    )

    # ── API keys belong to an app ────────────────────────────────────────────
    op.execute("""
        ALTER TABLE api_keys
            ADD COLUMN app_id uuid,
            ADD COLUMN environment varchar(10) NOT NULL DEFAULT 'live',
            ADD COLUMN legal_entity_ids jsonb,
            ADD COLUMN revoked_at timestamptz,
            ADD COLUMN revoked_by uuid,
            ADD COLUMN revoke_reason varchar(200),
            -- Addresses the key has been used from, so first use from a new one can be flagged.
            ADD COLUMN known_ips jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD CONSTRAINT ck_api_keys_environment CHECK (environment IN ('test', 'live'))
    """)
    op.execute(f"ALTER TABLE api_keys ADD {_fk('api_keys', 'app_id', 'connected_apps')}")
    op.execute("CREATE INDEX ix_api_keys_app ON api_keys (tenant_id, app_id)")

    op.execute(
        """
        CREATE TABLE external_identities (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id uuid NOT NULL,
            app_id uuid NOT NULL,
            external_id varchar(100) NOT NULL,
            employment_id uuid NOT NULL,
            user_account_id uuid,
            pending_manager_external_id varchar(100),
            last_source_updated_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            """
        + _fk("external_identities", "app_id", "connected_apps")
        + """,
            """
        + _fk("external_identities", "employment_id", "employments")
        + """
        )
    """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_external_identities_external "
        "ON external_identities (tenant_id, app_id, external_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_external_identities_employment "
        "ON external_identities (tenant_id, app_id, employment_id)"
    )
    op.execute(
        "CREATE INDEX ix_external_identities_employment "
        "ON external_identities (tenant_id, employment_id)"
    )
    op.execute(
        "CREATE INDEX ix_external_identities_pending_manager "
        "ON external_identities (tenant_id, app_id, pending_manager_external_id) "
        "WHERE pending_manager_external_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE integration_mappings (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id uuid NOT NULL,
            app_id uuid NOT NULL,
            kind varchar(20) NOT NULL,
            external_value varchar(200) NOT NULL,
            target_id uuid,
            target_value varchar(40),
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            """
        + _fk("integration_mappings", "app_id", "connected_apps")
        + """,
            CONSTRAINT ck_integration_mappings_kind
                CHECK (kind IN ('LEGAL_ENTITY', 'DEPARTMENT', 'LOCATION', 'DESIGNATION', 'ROLE')),
            CONSTRAINT ck_integration_mappings_target
                CHECK ((kind = 'ROLE' AND target_value IS NOT NULL)
                       OR (kind <> 'ROLE' AND target_id IS NOT NULL))
        )
    """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_integration_mappings_value "
        "ON integration_mappings (tenant_id, app_id, kind, lower(external_value))"
    )

    op.execute(
        """
        CREATE TABLE integration_profiles (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id uuid NOT NULL,
            app_id uuid NOT NULL,
            legal_entity_id uuid,
            version integer NOT NULL,
            status varchar(20) NOT NULL DEFAULT 'DRAFT',
            effective_from date,
            settings jsonb NOT NULL DEFAULT '{}'::jsonb,
            note varchar(500),
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            published_by uuid,
            published_at timestamptz,
            PRIMARY KEY (tenant_id, id),
            """
        + _fk("integration_profiles", "app_id", "connected_apps")
        + """,
            """
        + _fk("integration_profiles", "legal_entity_id", "legal_entities")
        + """,
            CONSTRAINT ck_integration_profiles_status
                CHECK (status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'DISCARDED')),
            CONSTRAINT ck_integration_profiles_published
                CHECK (status = 'DRAFT' OR status = 'DISCARDED' OR effective_from IS NOT NULL)
        )
    """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_integration_profiles_version ON integration_profiles "
        "(tenant_id, app_id, COALESCE(legal_entity_id, '00000000-0000-0000-0000-000000000000'), "
        "version)"
    )
    op.execute(
        "CREATE INDEX ix_integration_profiles_effective ON integration_profiles "
        "(tenant_id, app_id, legal_entity_id, status, effective_from)"
    )

    op.execute("""
        CREATE TABLE integration_requests (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id uuid NOT NULL,
            app_id uuid NOT NULL,
            api_key_id uuid,
            operation varchar(20) NOT NULL,
            external_id varchar(100),
            employment_id uuid,
            idempotency_key varchar(120),
            request_hash varchar(64),
            outcome varchar(20) NOT NULL,
            error_code varchar(60),
            error_detail jsonb,
            changes jsonb,
            warnings jsonb,
            response jsonb,
            http_status integer,
            duration_ms integer,
            request_id varchar(80),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id)
        )
    """)
    op.execute(
        "CREATE INDEX ix_integration_requests_recent "
        "ON integration_requests (tenant_id, app_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_integration_requests_external "
        "ON integration_requests (tenant_id, app_id, external_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_integration_requests_idempotency "
        "ON integration_requests (tenant_id, api_key_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL AND outcome NOT IN ('REJECTED', 'FAILED')"
    )

    op.execute("CREATE SEQUENCE integration_events_id_seq")
    op.execute("CREATE SEQUENCE integration_feed_seq")
    op.execute("""
        CREATE TABLE integration_events (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id bigint NOT NULL DEFAULT nextval('integration_events_id_seq'),
            event_type varchar(60) NOT NULL,
            employment_id uuid,
            subject_id uuid,
            payload jsonb NOT NULL,
            changes jsonb,
            origin_app_id uuid,
            joining_date date,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id)
        )
    """)
    op.execute("ALTER SEQUENCE integration_events_id_seq OWNED BY integration_events.id")
    op.execute(
        "CREATE INDEX ix_integration_events_employment "
        "ON integration_events (tenant_id, employment_id, occurred_at)"
    )
    op.execute(
        "CREATE INDEX ix_integration_events_occurred ON integration_events (tenant_id, occurred_at)"
    )
    op.execute(
        """
        CREATE TABLE integration_app_events (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            app_id uuid NOT NULL,
            event_id bigint NOT NULL,
            seq bigint,
            assigned_txid xid8,
            available_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, app_id, event_id),
            CONSTRAINT fk_integration_app_events_event FOREIGN KEY (tenant_id, event_id)
                REFERENCES integration_events(tenant_id, id) ON DELETE CASCADE,
            """
        + _fk("integration_app_events", "app_id", "connected_apps")
        + """,
            CONSTRAINT ck_integration_app_events_assigned
                CHECK ((seq IS NULL) = (assigned_txid IS NULL))
        )
    """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_integration_app_events_seq "
        "ON integration_app_events (tenant_id, app_id, seq) WHERE seq IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_integration_app_events_held "
        "ON integration_app_events (tenant_id, available_at) WHERE seq IS NULL"
    )
    op.execute(
        """
        CREATE TABLE integration_cursors (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            app_id uuid NOT NULL,
            position bigint NOT NULL DEFAULT 0,
            read_at timestamptz,
            -- Events up to this feed position were removed by retention; a reader still
            -- behind it must resync from the read API.
            purged_through bigint NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, app_id),
            """
        + _fk("integration_cursors", "app_id", "connected_apps")
        + """
        )
    """
    )

    op.execute(
        """
        CREATE TABLE possible_duplicates (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id uuid NOT NULL,
            app_id uuid NOT NULL,
            external_id varchar(100) NOT NULL,
            employment_id uuid NOT NULL,
            match_reason varchar(200) NOT NULL,
            payload jsonb,
            status varchar(20) NOT NULL DEFAULT 'OPEN',
            resolved_by uuid,
            resolved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, id),
            """
        + _fk("possible_duplicates", "app_id", "connected_apps")
        + """,
            """
        + _fk("possible_duplicates", "employment_id", "employments")
        + """,
            CONSTRAINT ck_possible_duplicates_status
                CHECK (status IN ('OPEN', 'SAME_PERSON', 'DIFFERENT_PERSON'))
        )
    """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_possible_duplicates_open ON possible_duplicates "
        "(tenant_id, app_id, external_id, employment_id) WHERE status = 'OPEN'"
    )

    op.execute("""
        CREATE TABLE integration_rate_windows (
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            api_key_id uuid NOT NULL,
            window_start timestamptz NOT NULL,
            -- Spread over a few rows, so concurrent calls with one key don't queue on one lock.
            shard smallint NOT NULL DEFAULT 0,
            count integer NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, api_key_id, window_start, shard)
        )
    """)

    op.execute("ALTER TABLE punches ADD COLUMN source_system varchar(40)")
    # When a future-dated hire was announced to connected apps, so applying it on its date
    # doesn't announce it a second time.
    op.execute("ALTER TABLE personnel_actions ADD COLUMN integration_announced_at timestamptz")
    # Onboarding checklist tasks that tick themselves when a connected app has the new joiner.
    op.execute("ALTER TABLE onboarding_items ADD COLUMN integration_app_id uuid")
    op.execute(
        "CREATE INDEX ix_onboarding_items_integration ON onboarding_items "
        "(tenant_id, integration_app_id) WHERE integration_app_id IS NOT NULL"
    )

    # ── Existing ERP links move to external_identities ───────────────────────
    op.execute("""
        INSERT INTO connected_apps (tenant_id, id, code, name, kind)
        SELECT systems.tenant_id, gen_random_uuid(), systems.code, systems.code, 'TWO_WAY'
        FROM (
            SELECT DISTINCT ua.tenant_id,
                   upper(regexp_replace(ua.erp_system, '[^A-Za-z0-9_]', '_', 'g')) AS code
            FROM user_accounts ua
            WHERE ua.erp_system IS NOT NULL AND ua.erp_user_id IS NOT NULL
              AND ua.employment_id IS NOT NULL
        ) systems
        WHERE systems.code ~ '^[A-Z][A-Z0-9_]{1,39}$'
    """)
    op.execute("""
        INSERT INTO external_identities
            (tenant_id, id, app_id, external_id, employment_id, user_account_id)
        SELECT ua.tenant_id, gen_random_uuid(), ca.id, ua.erp_user_id, ua.employment_id, ua.id
        FROM user_accounts ua
        JOIN connected_apps ca
          ON ca.tenant_id = ua.tenant_id
         AND ca.code = upper(regexp_replace(ua.erp_system, '[^A-Za-z0-9_]', '_', 'g'))
        WHERE ua.erp_user_id IS NOT NULL AND ua.employment_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    # The copied rows' deferred foreign-key checks must run before the tables are altered.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")

    # ── Row-level security and grants ────────────────────────────────────────
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            "(tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id())"
        )
    op.execute("ALTER TABLE api_keys FORCE ROW LEVEL SECURITY")
    # The sync log is evidence: the app may add rows and the retention job may delete old ones,
    # but nothing may rewrite one.
    op.execute(f"REVOKE UPDATE ON integration_requests FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON integration_requests TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE integration_events_id_seq TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE integration_feed_seq TO {APP_ROLE}")

    # A key arrives before any tenant is known. This exposes only what authenticating it needs.
    op.execute("""
        CREATE FUNCTION integration_key_lookup(p_hash text)
        RETURNS TABLE(
            tenant_id uuid,
            key_id uuid,
            app_id uuid,
            app_code text,
            app_kind text,
            app_status text,
            scopes jsonb,
            allowed_ips jsonb,
            legal_entity_ids jsonb,
            environment text,
            is_active boolean,
            expires_at timestamptz,
            revoked_at timestamptz,
            rate_limit_per_minute integer,
            known_ips jsonb,
            tenant_status text,
            tenant_archived_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT k.tenant_id, k.id, k.app_id, ca.code, ca.kind, ca.status, k.scopes,
                   k.allowed_ips, k.legal_entity_ids, k.environment, k.is_active, k.expires_at,
                   k.revoked_at, k.rate_limit_per_minute, k.known_ips, t.status, t.archived_at
            FROM api_keys k
            JOIN connected_apps ca ON ca.tenant_id = k.tenant_id AND ca.id = k.app_id
            JOIN tenants t ON t.id = k.tenant_id
            WHERE k.key_hash = p_hash
            LIMIT 1
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION integration_key_lookup(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION integration_key_lookup(text) TO {APP_ROLE}")

    # Aggregate health per app for /metrics (alerts), across tenants: numbers only, no
    # personal data, so a scrape needs no tenant context.
    op.execute("""
        CREATE FUNCTION integration_health()
        RETURNS TABLE(
            tenant text,
            app text,
            feed_lag bigint,
            feed_read_at timestamptz,
            held_exits bigint,
            unlinked_hires bigint,
            next_key_expiry timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT t.slug, ca.code,
                   (SELECT count(*) FROM integration_app_events ae
                    WHERE ae.tenant_id = ca.tenant_id AND ae.app_id = ca.id AND ae.seq IS NOT NULL
                      AND ae.seq > COALESCE(c.position, 0)),
                   c.read_at,
                   (SELECT count(*) FROM integration_requests r
                    WHERE r.tenant_id = ca.tenant_id AND r.app_id = ca.id
                      AND r.operation = 'EXIT' AND r.outcome = 'HELD_FOR_REVIEW'
                      AND NOT EXISTS (SELECT 1 FROM integration_requests d
                                      WHERE d.tenant_id = r.tenant_id
                                        AND d.operation IN ('EXIT_RELEASED', 'EXIT_REJECTED')
                                        AND d.error_detail->>'held_request_id' = r.id::text)),
                   (SELECT count(DISTINCT ev.employment_id) FROM integration_events ev
                    JOIN integration_app_events ae ON ae.tenant_id = ev.tenant_id
                     AND ae.event_id = ev.id AND ae.app_id = ca.id
                    JOIN employments e ON e.tenant_id = ev.tenant_id AND e.id = ev.employment_id
                    WHERE ev.tenant_id = ca.tenant_id AND ev.event_type = 'employee.hired'
                      AND ev.origin_app_id IS NULL
                      AND ev.occurred_at < now() - interval '24 hours'
                      AND e.employment_state <> 'SEPARATED'
                      AND NOT EXISTS (SELECT 1 FROM external_identities x
                                      WHERE x.tenant_id = e.tenant_id AND x.app_id = ca.id
                                        AND x.employment_id = e.id)),
                   (SELECT min(k.expires_at) FROM api_keys k
                    WHERE k.tenant_id = ca.tenant_id AND k.app_id = ca.id AND k.is_active
                      AND k.revoked_at IS NULL)
            FROM connected_apps ca
            JOIN tenants t ON t.id = ca.tenant_id
            LEFT JOIN integration_cursors c ON c.tenant_id = ca.tenant_id AND c.app_id = ca.id
            WHERE ca.status = 'ACTIVE' AND t.status = 'ACTIVE'
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION integration_health() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION integration_health() TO {APP_ROLE}")


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS integration_health()")
    op.execute("DROP FUNCTION IF EXISTS integration_key_lookup(text)")
    op.execute("ALTER TABLE punches DROP COLUMN IF EXISTS source_system")
    op.execute("ALTER TABLE personnel_actions DROP COLUMN IF EXISTS integration_announced_at")
    op.execute("DROP INDEX IF EXISTS ix_onboarding_items_integration")
    op.execute("ALTER TABLE onboarding_items DROP COLUMN IF EXISTS integration_app_id")
    for table in (
        "integration_rate_windows",
        "possible_duplicates",
        "integration_cursors",
        "integration_app_events",
        "integration_events",
        "integration_requests",
        "integration_profiles",
        "integration_mappings",
        "external_identities",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP SEQUENCE IF EXISTS integration_feed_seq")
    op.execute("ALTER TABLE api_keys NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_api_keys_app")
    op.execute("""
        ALTER TABLE api_keys
            DROP CONSTRAINT IF EXISTS fk_api_keys_app_id,
            DROP CONSTRAINT IF EXISTS ck_api_keys_environment,
            DROP COLUMN IF EXISTS app_id,
            DROP COLUMN IF EXISTS environment,
            DROP COLUMN IF EXISTS legal_entity_ids,
            DROP COLUMN IF EXISTS revoked_at,
            DROP COLUMN IF EXISTS revoked_by,
            DROP COLUMN IF EXISTS revoke_reason,
            DROP COLUMN IF EXISTS known_ips
    """)
    op.execute("DROP TABLE IF EXISTS connected_apps")

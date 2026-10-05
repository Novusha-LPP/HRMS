"""Bounded daily report snapshots, with stable paging and export."""
from alembic import op
revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE daily_report_snapshots (
        tenant_id uuid NOT NULL REFERENCES tenants(id), id uuid NOT NULL,
        user_id uuid NOT NULL, scope_key text NOT NULL, work_date date NOT NULL,
        generated_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
        summary jsonb NOT NULL, PRIMARY KEY(tenant_id,id),
        FOREIGN KEY(tenant_id,user_id) REFERENCES user_accounts(tenant_id,id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX daily_report_expiry ON daily_report_snapshots(tenant_id,expires_at)")
    op.execute("""CREATE TABLE daily_report_rows (
        tenant_id uuid NOT NULL, snapshot_id uuid NOT NULL, position integer NOT NULL,
        payload jsonb NOT NULL, PRIMARY KEY(tenant_id,snapshot_id,position),
        FOREIGN KEY(tenant_id,snapshot_id) REFERENCES daily_report_snapshots(tenant_id,id)
        ON DELETE CASCADE
    )""")
    for table in ("daily_report_snapshots", "daily_report_rows"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING "
                   "(tenant_id=current_tenant_id()) WITH CHECK (tenant_id=current_tenant_id())")


def downgrade():
    op.drop_table("daily_report_rows")
    op.drop_table("daily_report_snapshots")

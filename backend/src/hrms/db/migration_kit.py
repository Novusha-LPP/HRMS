"""
SQL builders for migrations, so a migration follows docs/database-conventions.md by default.

Every function returns SQL (a string or a list of strings) and runs nothing itself, so a
migration stays readable and the SQL can be tested without Alembic:

    from hrms.db import migration_kit as kit

    def upgrade():
        for sql in kit.tenant_table("widgets", "name varchar(100) NOT NULL, owner_by uuid",
                                    comment="Widgets a tenant configures.",
                                    references={"owner_by": "user_accounts"}):
            op.execute(sql)

Rules for changing this module: migrations that already ran call these functions every time
the migration chain is replayed (CI, a new environment), so a function must keep producing the
same SQL for the same arguments. Add a parameter with a backward-compatible default, or a new
function — never change what an existing call emits.

A migration never imports app enums or conventions.py: copy the values in literally
(`check_in("status", ("ACTIVE", "INACTIVE"))`). The schema rules check that the CHECK still
matches the enum at head.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

APP_ROLE = "hrms_app"
POLICY = "tenant_id = current_tenant_id()"
HALF_DAY = "{col} * 2 = trunc({col} * 2)"


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ident(name: str) -> str:
    """
    A constraint or index name, refused if PostgreSQL would silently truncate it (63 bytes):
    the object would be created under the cut name and a later VALIDATE or DROP by the full
    name would not find it.
    """
    if len(name.encode()) > 63:
        raise ValueError(f"identifier longer than 63 bytes, pass a shorter name: {name}")
    return name


# ── Tables ──────────────────────────────────────────────────────────────────────────────────


def tenant_table(
    name: str,
    columns: str,
    *,
    comment: str,
    references: dict[str, str] | None = None,
    append_only: bool = False,
    cascade_with_tenant: bool = False,
) -> list[str]:
    """
    A tenant-scoped table: PK (tenant_id, id), the tenants FK, a tenant-aware FK and index per
    reference, forced row-level security with the standard policy, and a comment.

    `columns` is the SQL for the table's own columns (not tenant_id or id). `references` maps a
    column to the table it points at. `cascade_with_tenant` must match
    conventions.TENANT_CASCADE.
    """
    references = references or {}
    on_delete = " ON DELETE CASCADE" if cascade_with_tenant else ""
    body = [
        f"tenant_id uuid NOT NULL REFERENCES tenants(id){on_delete}",
        "id uuid NOT NULL",
        columns.strip().rstrip(","),
        "PRIMARY KEY (tenant_id, id)",
        *(tenant_fk(name, col, target) for col, target in references.items()),
    ]
    statements = [f"CREATE TABLE {name} (\n    " + ",\n    ".join(body) + "\n)"]
    statements += [index(name, ["tenant_id", col]) for col in references]
    statements += enable_tenant_rls(name)
    if append_only:
        statements.append(make_append_only(name))
    statements.append(table_comment(name, comment))
    return statements


def enable_tenant_rls(table: str) -> list[str]:
    """Forced row-level security with the one standard policy (rule L2)."""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {table} USING ({POLICY}) WITH CHECK ({POLICY})",
    ]


def replace_tenant_policy(table: str) -> list[str]:
    """Swap whatever policies a table has for the standard one (rule L2)."""
    return [
        f"""DO $$
DECLARE p record;
BEGIN
  FOR p IN SELECT polname FROM pg_policy WHERE polrelid = '{table}'::regclass LOOP
    EXECUTE format('DROP POLICY %I ON {table}', p.polname);
  END LOOP;
END $$""",
        *enable_tenant_rls(table),
    ]


def make_append_only(table: str) -> str:
    """The runtime role may add and read rows, never change or remove them (rule L10)."""
    return f"REVOKE UPDATE, DELETE ON {table} FROM {APP_ROLE}"


def table_comment(table: str, text: str) -> str:
    return f"COMMENT ON TABLE {table} IS {_quote(text)}"


# ── Constraints ─────────────────────────────────────────────────────────────────────────────


def tenant_fk(table: str, column: str, target: str, *, on_delete: str = "") -> str:
    """A constraint clause referencing target(tenant_id, id), for use inside CREATE TABLE."""
    action = f" ON DELETE {on_delete}" if on_delete else ""
    return (
        f"CONSTRAINT {_ident(f'fk_{table}_{column}')} FOREIGN KEY (tenant_id, {column}) "
        f"REFERENCES {target}(tenant_id, id){action} DEFERRABLE INITIALLY DEFERRED"
    )


def add_tenant_fk(table: str, column: str, target: str, *, on_delete: str = "") -> list[str]:
    """
    Add a tenant-aware FK to an existing table without a long lock: NOT VALID takes a brief
    lock, then VALIDATE checks existing rows while writes continue.
    """
    clause = tenant_fk(table, column, target, on_delete=on_delete)
    return [
        f"ALTER TABLE {table} ADD {clause} NOT VALID",
        f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_{column}",
    ]


def check_in(column: str, values: Iterable[str]) -> str:
    """A CHECK expression allowing exactly `values` (copied literally into the migration)."""
    listed = ", ".join(_quote(v) for v in values)
    return f"{column} IN ({listed})"


def half_day(column: str) -> str:
    """A CHECK expression: a whole or half day (DB-D2)."""
    return HALF_DAY.format(col=column)


def add_check(table: str, name: str, expression: str) -> list[str]:
    """Add a CHECK to an existing table: NOT VALID, then VALIDATE (no long lock)."""
    _ident(name)
    return [
        f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID",
        f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}",
    ]


def effective_range_check(table: str, *, strict: bool = False) -> list[str]:
    """
    effective_to not before effective_from (rule L8).

    The default (>=) allows a one-day row under an inclusive end, and the empty row a same-day
    change leaves under an exclusive end. strict=True (>) is for exclusive-end tables that must
    never hold an empty row, such as salary history.
    """
    op = ">" if strict else ">="
    return add_check(
        table,
        f"ck_{table}_effective_range",
        f"effective_to IS NULL OR effective_to {op} effective_from",
    )


def no_overlap(
    table: str,
    name: str,
    keys: Sequence[str],
    *,
    end_inclusive: bool,
    where: str | None = None,
    deferred: bool = False,
) -> str:
    """
    No two rows with the same keys may apply on the same day (rule L8). `end_inclusive` must
    match the table's entry in conventions.EFFECTIVE_END_INCLUSIVE / _EXCLUSIVE: it decides
    whether the handover day belongs to the old row ('[]') or only to the new one ('[)').
    Needs the btree_gist extension (installed by migration 0001). Pass deferred=True where the
    app ends the old row and adds the new one in the same save: the check then runs at commit,
    so the order of the two statements doesn't matter.
    """
    bounds = "'[]'" if end_inclusive else "'[)'"
    parts = ", ".join(f"{k} WITH =" for k in ("tenant_id", *keys))
    period = f"daterange(effective_from, COALESCE(effective_to, '9999-12-31'::date), {bounds})"
    predicate = f" WHERE ({where})" if where else ""
    timing = " DEFERRABLE INITIALLY DEFERRED" if deferred else ""
    return (
        f"ALTER TABLE {table} ADD CONSTRAINT {_ident(name)} "
        f"EXCLUDE USING gist ({parts}, {period} WITH &&){predicate}{timing}"
    )


# ── Indexes ─────────────────────────────────────────────────────────────────────────────────


def _index_name(table: str, columns: Sequence[str]) -> str:
    return "ix_" + table + "_" + "_".join(c for c in columns if c != "tenant_id")


def index(
    table: str,
    columns: Sequence[str],
    *,
    name: str | None = None,
    unique: bool = False,
    where: str | None = None,
    concurrently: bool = False,
) -> str:
    """
    CREATE INDEX. Pass concurrently=True for a table that already holds data, and run it
    outside the migration's transaction:

        with op.get_context().autocommit_block():
            op.execute(kit.index("punches", ["tenant_id", "work_date"], concurrently=True))

    There is deliberately no IF NOT EXISTS: a concurrent build that fails leaves an INVALID
    index behind, and IF NOT EXISTS would skip it silently. A rerun fails loudly instead; drop
    the leftover (kit.drop_index(name, concurrently=True)) and run the migration again.
    """
    kind = "UNIQUE INDEX" if unique else "INDEX"
    how = " CONCURRENTLY" if concurrently else ""
    predicate = f" WHERE {where}" if where else ""
    return (
        f"CREATE {kind}{how} {_ident(name or _index_name(table, columns))} "
        f"ON {table} ({', '.join(columns)}){predicate}"
    )


def drop_index(name: str, *, concurrently: bool = False) -> str:
    """DROP INDEX; concurrently=True (outside a transaction) for a table in use."""
    how = " CONCURRENTLY" if concurrently else ""
    return f"DROP INDEX{how} IF EXISTS {name}"


# ── Change history ──────────────────────────────────────────────────────────────────────────


def record_changes(table: str, entity_type: str) -> str:
    """
    Field-level change history for a master-data table (migration 0062): every insert,
    update, archive and delete writes an entity_change_log row, whatever path made it.
    Add entity_type to core/change_audit.ENTITY_TYPES as well.
    """
    return (
        f"CREATE TRIGGER {_ident(f'record_{table}_change')} "
        f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION record_row_change({_quote(entity_type)})"
    )

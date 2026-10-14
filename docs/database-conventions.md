# Database conventions

These rules hold for every table. CI checks them against the real, migrated database
(`backend/tests/test_schema_conventions.py`), so a migration that breaks one fails its PR.

**Exceptions.** A deliberate exception goes in `backend/src/hrms/db/conventions.py`, with its reason. An entry that stops matching anything is reported too.

**Known debt.** Debt from before the rules existed is listed in `backend/tests/schema_baseline.txt`. That list may only shrink. When you fix an entry, delete its line; the test fails if you forget.

```bash
# from backend/, against a private migrated database (never a shared one)
python -m hrms.db.schema_rules                                  # list current violations
python -m hrms.db.schema_rules --write tests/schema_baseline.txt  # rewrite; review the diff
```

## The rules

| Rule | Every table … | How to comply |
|---|---|---|
| **L1** | has a primary key; a tenant table's starts with `tenant_id` | `kit.tenant_table()` |
| **L2** | is tenant-scoped, unless it is listed in `GLOBAL_TABLES`. A tenant table references `tenants`, has row-level security **enabled and forced**, and has exactly one policy: `tenant_id = current_tenant_id()` | `kit.tenant_table()`, `kit.replace_tenant_policy()` |
| **L3** | references other tenant tables through `(tenant_id, id)`, so a row can't point into another tenant. Only `TENANT_CASCADE` tables cascade from `tenants` | `kit.tenant_fk()` / `kit.add_tenant_fk()` |
| **L4** | gives every `uuid` column named `*_id` or `*_by` a foreign key, unless it is listed in `SOFT_REFERENCES` (polymorphic or log columns) | `references={...}` |
| **L5** | indexes every foreign key by its own columns (`tenant_id, col`) | automatic in `tenant_table()`; `kit.index()` |
| **L6** | stores exact numbers only, never `real` or `double precision`. Leave quantities are whole or half days: `numeric(6,1)` with `kit.half_day()` | `numeric(p,s)` |
| **L7** | lists every status, type or kind column in `DOMAINS` (pointing at its Python `StrEnum`) or in `DOMAIN_EXEMPT`. The column's CHECK allows exactly the enum's values | `kit.check_in()` with the values copied in |
| **L8** | gives each effective-dated table a range CHECK and a no-overlap guard whose bounds match its declared end semantics (see below) | `kit.effective_range_check()`, `kit.no_overlap()` |
| **L9** | has no index duplicated by another index's leading columns | drop the shorter one |
| **L10** | `APPEND_ONLY` history can't be updated or deleted by `hrms_app`, and `PLATFORM_ONLY` tables can't be touched by it at all | `append_only=True` / `kit.make_append_only()` |
| **L11** | `SECURITY DEFINER` functions set `search_path` | `SET search_path = public` |
| **L12** | uses `timestamptz` and `jsonb`; no `NOT VALID` constraint is left at head | — |
| **L13** | has a `COMMENT ON TABLE` saying what it holds | `comment=` / `kit.table_comment()` |
| **L14** | (with `archived_at`) has unique keys that say whether archived rows count: either `WHERE archived_at IS NULL`, or an entry in `ARCHIVE_UNIQUE_INCLUDES_ARCHIVED` | `where=` |

## Effective dating

`effective_to` means one of two things, and each table declares which:

| Semantics | Meaning | Close the old row with | Range CHECK | No-overlap bounds | Tables |
|---|---|---|---|---|---|
| **Exclusive** | the row stops applying *on* `effective_to` | `effective_to = new.effective_from` | `effective_to > effective_from` | `'[)'` | `EFFECTIVE_END_EXCLUSIVE` |
| **Inclusive** | the row still applies *on* `effective_to` | `effective_to = new.effective_from - 1 day` | `effective_to >= effective_from` | `'[]'` | `EFFECTIVE_END_INCLUSIVE` |

Readers follow the same choice: `effective_to > :day` for exclusive tables, `effective_to >= :day` for inclusive ones. Mixing them makes two rows apply on the handover day.

## Writing a migration

- **Expand, then contract.** Add first, and switch the code over. Drop only in a later release, because the testing database holds real employee data.
- **No long locks.** Migrations run with `lock_timeout = 5s` (`HRMS_MIGRATION_LOCK_TIMEOUT`) and fail rather than queue every request behind them.
  - Add CHECKs and FKs to existing tables with `kit.add_check()` / `kit.add_tenant_fk()` (`NOT VALID`, then `VALIDATE`).
  - Build indexes on tables that hold data with `kit.index(..., concurrently=True)` inside `op.get_context().autocommit_block()`.
- **Measure before you constrain.** Add the new constraint's violation count to `scripts/db_preflight.py` (arriving with DB-1 step W1), and run it (read-only) on the testing database before the migration ships.
- **Freeze values.** A migration never imports app enums or `conventions.py`. Copy the values in. The schema rules check that they still match the enum.
- **Changing `migration_kit`.** Migrations that already ran call it every time the chain is replayed. Never change the SQL an existing call produces; add a parameter with a compatible default, or a new function.

## When a migration fails during a deploy

Each migration runs in its own transaction. A failure therefore leaves the database at the last migration that completed, and the API keeps running the old code: `deploy/compose.yml` only starts the new API after `migrate` succeeds, and expand-only migrations keep the old code working.

| Symptom | Cause | What to do |
|---|---|---|
| `canceling statement due to lock timeout` | Live traffic held a lock for more than 5 s | Run the deploy again at a quieter moment. To wait longer for one run, set `HRMS_MIGRATION_LOCK_TIMEOUT=30s`. |
| `relation "ix_…" already exists` on a concurrent index | An earlier concurrent build failed and left an INVALID index | Run `DROP INDEX CONCURRENTLY ix_…;`, then deploy again. CI's rule L12 reports invalid indexes. |
| `canceling statement due to statement timeout` | A backfill ran longer than 15 min | Split the backfill into batches, or set `HRMS_MIGRATION_STATEMENT_TIMEOUT` for that run. |

## PR checklist

- [ ] Built with `migration_kit` (`tenant_table`, `tenant_fk`, `check_in`, …).
- [ ] New constraints on existing tables are added `NOT VALID` → `VALIDATE`, and indexes `CONCURRENTLY`.
- [ ] Expand only. Any drop is scheduled for a later release.
- [ ] A new enum value goes into the `StrEnum` **and** into a migration that updates the CHECK (L7 fails otherwise).
- [ ] The constraint has a check in `db_preflight.py` (once W1 has landed).
- [ ] `test_schema_conventions.py` is green without new lines in `schema_baseline.txt`.
- [ ] A new master-data table has a `version` column, its PATCH calls `core/versioning.require_version`, and it records its changes (`kit.record_changes`).
- [ ] A constraint users can trigger has a message in `core/error_handlers.CONSTRAINT_MESSAGES`.
- [ ] A new column that points at a row without a foreign key (in `SOFT_REFERENCES`) has a check in `hrms/db/integrity.py`, so the nightly job notices when its target disappears.
- [ ] The schema diagram is regenerated: `python scripts/schema_diagram.py` (`tests/test_schema_diagram.py` fails otherwise).
- [ ] `downgrade()` works, or the migration is listed as irreversible in `scripts/check_migrations.py`.

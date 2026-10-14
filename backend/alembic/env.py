import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from hrms.alembic_hooks import compare_type, include_object
from hrms.core.config import settings
from hrms.model_registry import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ensure database URL is sourced from environment or config settings
db_url = os.environ.get("HRMS_DATABASE_URL") or settings.database_url
if db_url:
    # configparser reads "%" as interpolation; a percent-encoded password or socket path
    # would otherwise make Alembic fail before connecting.
    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

target_metadata = metadata
AUTOGENERATE_PLUGINS = ["alembic.autogenerate.*", "~alembic.autogenerate.comments"]


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=compare_type,
        # Table comments belong to migrations (rule L13 checks every table has one), not to the
        # models, so they aren't compared.
        autogenerate_plugins=AUTOGENERATE_PLUGINS,
    )
    with context.begin_transaction():
        context.run_migrations()


# A migration waits at most this long for a lock, then fails instead of queueing every request
# behind it; run it again when traffic is quieter (docs/database-conventions.md).
LOCK_TIMEOUT = os.environ.get("HRMS_MIGRATION_LOCK_TIMEOUT", "5s")
STATEMENT_TIMEOUT = os.environ.get("HRMS_MIGRATION_STATEMENT_TIMEOUT", "15min")


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    connection.execute(text("SELECT set_config('lock_timeout', :v, false)"), {"v": LOCK_TIMEOUT})
    connection.execute(
        text("SELECT set_config('statement_timeout', :v, false)"), {"v": STATEMENT_TIMEOUT}
    )
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=compare_type,
        # Table comments belong to migrations (rule L13 checks every table has one), not to the
        # models, so they aren't compared.
        autogenerate_plugins=AUTOGENERATE_PLUGINS,
        # One transaction per migration: a failure leaves the database at the last revision
        # that completed, and migration_kit.index(concurrently=True) can run outside one.
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Isolated migration boundary checks. Never accepts a shared employee database."""
import asyncio
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def provision():
    url = make_url(os.environ["HRMS_TEST_DATABASE_URL"])
    if not (url.database or "").endswith("_test"):
        raise RuntimeError("Migration checks require an isolated *_test database")
    scratch = "migration_" + uuid4().hex + "_test"
    engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    await engine.dispose()
    return url.set(database=scratch), url


async def populate(url):
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("""INSERT INTO tenants (id,slug,display_name,status,plan)
            VALUES ('11111111-1111-1111-1111-111111111111','migration-check','Migration check',
                    'ACTIVE','STARTER')"""))
    await engine.dispose()


async def destroy(url, owner):
    engine = create_async_engine(owner.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE "{url.database}" WITH (FORCE)'))
    await engine.dispose()


def main():
    url, owner = asyncio.run(provision())
    old = os.environ.get("HRMS_DATABASE_URL")
    os.environ["HRMS_DATABASE_URL"] = url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "0037")
        command.downgrade(config, "0016")
        command.upgrade(config, "0037")
        asyncio.run(populate(url))
        command.upgrade(config, "head")
        command.check(config)
        try:
            command.downgrade(config, "0037")
        except RuntimeError as exc:
            if not any(word in str(exc).lower() for word in ("checkpoint", "enrollment")):
                raise
        else:
            raise AssertionError("Data-preserving rollback boundary must reject schema removal")
        print("Migration boundaries: reversible rollback, populated upgrade, schema check passed")
    finally:
        if old is None:
            os.environ.pop("HRMS_DATABASE_URL", None)
        else:
            os.environ["HRMS_DATABASE_URL"] = old
        asyncio.run(destroy(url, owner))


if __name__ == "__main__":
    main()

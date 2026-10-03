"""
Deployment steps, run by the deploy's one-shot `migrate` service before the API starts:

    python -m hrms.deploy migrate

1. Applies every migration (alembic upgrade head), as the database owner.
2. Sets the hrms_app role's password from HRMS_APP_ROLE_PASSWORD. Migration 0005 creates the
   role with a published development password; a deployed environment must never keep it.

Both are idempotent, so every deploy runs them.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core.config import KNOWN_DEV_APP_ROLE_PASSWORD, settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
# Goes into a connection URL as-is and into ALTER ROLE as a literal, so keep it simple.
SAFE_PASSWORD = re.compile(r"[A-Za-z0-9_-]{24,}")


def _app_role_password() -> str | None:
    password = os.environ.get("HRMS_APP_ROLE_PASSWORD")
    if not password:
        if settings.is_deployed:
            raise SystemExit("HRMS_APP_ROLE_PASSWORD is required outside local development")
        return None
    if password == KNOWN_DEV_APP_ROLE_PASSWORD or not SAFE_PASSWORD.fullmatch(password):
        raise SystemExit(
            "HRMS_APP_ROLE_PASSWORD must be 24+ characters of A-Z a-z 0-9 _ - "
            "(e.g. `openssl rand -hex 32`) and not the published development password"
        )
    return password


async def _set_app_role_password(password: str) -> None:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            # Validated above to [A-Za-z0-9_-], so it can't break out of the literal.
            await conn.execute(text(f"ALTER ROLE hrms_app PASSWORD '{password}'"))
    finally:
        await engine.dispose()


def migrate() -> None:
    password = _app_role_password()  # fail before touching the schema
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    command.upgrade(config, "head")
    if password:
        asyncio.run(_set_app_role_password(password))
        print("hrms_app password set from HRMS_APP_ROLE_PASSWORD")


def main(argv: list[str]) -> int:
    if argv == ["migrate"]:
        migrate()
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

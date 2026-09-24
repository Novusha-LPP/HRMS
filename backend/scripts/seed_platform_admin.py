"""
Bootstrap the first platform admin — the role above every tenant that can
register a company as its own new tenant, or link one in as a subsidiary of
an existing tenant. See core/tenant_provisioning.py and
modules/platform/router.py.

There is deliberately no signup flow for this: unlike a tenant's first
SUPER_ADMIN (POST /v1/auth/register-company, self-serve), a platform admin
sits above the whole isolation model, so the first one has to be seeded the
same way migrations are applied — connecting directly as the Postgres
superuser, never through the restricted hrms_app role.

Usage:
    uv run python scripts/seed_platform_admin.py [email] [password] [name]
    (all optional — defaults to a fixed dev account, printed on completion)
"""

import asyncio
import sys
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hrms.core.config import settings
from hrms.core.security import hash_password

DEFAULT_EMAIL = "platform@hrms.internal"
DEFAULT_PASSWORD = "Passw0rd!"
DEFAULT_NAME = "Platform Admin"

engine = create_async_engine(settings.database_url)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL
    password = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PASSWORD
    name = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_NAME

    async with Session() as session:
        existing = (
            await session.execute(text("SELECT id FROM platform_admins WHERE lower(email) = lower(:email)"), {"email": email})
        ).first()
        if existing:
            await session.execute(
                text("UPDATE platform_admins SET password_hash = :pw, name = :name, status = 'ACTIVE' WHERE lower(email) = lower(:email)"),
                {"pw": hash_password(password), "name": name, "email": email},
            )
            print(f"Updated existing platform admin {email}.")
        else:
            await session.execute(
                text("""
                    INSERT INTO platform_admins (id, email, name, password_hash, status)
                    VALUES (:id, :email, :name, :pw, 'ACTIVE')
                """),
                {"id": str(uuid4()), "email": email, "name": name, "pw": hash_password(password)},
            )
            print(f"Created platform admin {email}.")
        await session.commit()

    print(f"\nSign in at /platform/login with:\n  email:    {email}\n  password: {password}\n")


if __name__ == "__main__":
    asyncio.run(main())

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
    uv run python scripts/seed_platform_admin.py <email> [name]
    HRMS_PLATFORM_ADMIN_PASSWORD='...' uv run python scripts/seed_platform_admin.py <email> [name]

The password comes from HRMS_PLATFORM_ADMIN_PASSWORD (kept out of shell history and the process
list) or, failing that, a random one is generated and printed ONCE. There is no default password.

  * New admin: created ACTIVE.
  * Existing admin: left exactly as it is, unless you supply a password (then only the password
    is replaced) — it is never silently reset, and a suspended admin is never reactivated
    without --reactivate.
"""

import argparse
import asyncio
import os
import secrets
import sys
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hrms.core.config import settings
from hrms.core.security import hash_password


async def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a platform admin")
    parser.add_argument("email")
    parser.add_argument("name", nargs="?", default="Platform Admin")
    parser.add_argument(
        "--reactivate", action="store_true", help="Also reactivate a suspended admin"
    )
    args = parser.parse_args()

    password = os.environ.get("HRMS_PLATFORM_ADMIN_PASSWORD")
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(16)
    if len(password) < 12 and settings.environment == "production":
        print("Refusing a password shorter than 12 characters in production.")
        return 2

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        existing = (
            await session.execute(
                text("SELECT id, status FROM platform_admins WHERE lower(email) = lower(:email)"),
                {"email": args.email},
            )
        ).first()
        if existing is None:
            await session.execute(
                text("""
                    INSERT INTO platform_admins (id, email, name, password_hash, status)
                    VALUES (:id, :email, :name, :pw, 'ACTIVE')
                """),
                {
                    "id": str(uuid4()),
                    "email": args.email,
                    "name": args.name,
                    "pw": hash_password(password),
                },
            )
            print(f"Created platform admin {args.email}.")
        else:
            if generated and not args.reactivate:
                print(
                    f"{args.email} already exists — left unchanged. Supply "
                    "HRMS_PLATFORM_ADMIN_PASSWORD to replace its password, or --reactivate to "
                    "re-enable a suspended admin."
                )
                await engine.dispose()
                return 0
            if not generated:
                await session.execute(
                    text("UPDATE platform_admins SET password_hash = :pw WHERE id = :id"),
                    {"pw": hash_password(password), "id": existing[0]},
                )
                print(f"Replaced the password of {args.email}.")
            if args.reactivate and existing[1] != "ACTIVE":
                await session.execute(
                    text("UPDATE platform_admins SET status = 'ACTIVE' WHERE id = :id"),
                    {"id": existing[0]},
                )
                print(f"Reactivated {args.email}.")
        await session.commit()
    await engine.dispose()

    if generated:
        print(
            f"\nSign in at /platform/login with:\n  email:    {args.email}\n"
            f"  password: {password}\n(shown once — store it now)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

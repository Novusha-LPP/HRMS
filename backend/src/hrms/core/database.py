"""
Async SQLAlchemy engine + session factory with per-transaction tenant isolation.

Every session runs SET LOCAL app.tenant_id = '<uuid>' before any statement so
PostgreSQL row-level security policies can read the tenant from current_setting().
This is a real second layer, not just decoration: the engine connects as
hrms_app (see migration 0005), a role with NOSUPERUSER and NOBYPASSRLS, so a
bug that forgets a WHERE tenant_id = ... clause still can't read another
tenant's rows — Postgres itself refuses.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import text

from hrms.core.config import settings
from hrms.core.tenancy import TenantDep

engine = create_async_engine(
    settings.app_database_url or settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.debug,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session(tenant_id: TenantDep) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a session with the tenant context already set in PostgreSQL.
    This makes RLS policies active for the life of the session.

    Declaring `tenant_id: TenantDep` here (rather than reading a ContextVar
    a sibling dependency happens to have set) means this is correct no
    matter what else a route declares or which order it declares them in —
    FastAPI resolves this function's own sub-dependencies for us.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        # Suspension/archival is checked here too, not just at login — a
        # platform admin suspending a tenant mid-session should cut off its
        # already-issued tokens on their very next request, not wait out an
        # up-to-8h JWT. tenants has no RLS, so this SELECT is unaffected by
        # the set_config just above.
        row = (
            await session.execute(text("SELECT status, archived_at FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)})
        ).mappings().first()
        if not row or row["status"] != "ACTIVE" or row["archived_at"] is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This company's account is suspended")
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_anonymous_session() -> AsyncGenerator[AsyncSession, None]:
    """
    For POST /v1/auth/login only — the one request that runs before any
    tenant or user identity is known. app.tenant_id is deliberately left
    unset, so ordinary RLS-scoped tables return nothing through this
    session; the login handler may only call the login_lookup() SECURITY
    DEFINER function (migration 0005), which exposes just the columns
    login needs and nothing else.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


AnonymousSessionDep = Annotated[AsyncSession, Depends(get_anonymous_session)]

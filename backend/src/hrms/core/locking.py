"""Transaction locks for operations that span several rows or create missing rows."""

from sqlalchemy import text


async def lock_resource(session, tenant_id, resource: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{tenant_id}:{resource}"},
    )

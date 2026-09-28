"""Apply due personnel actions; suitable for a daily scheduler using the runtime DB role."""
import asyncio
from hrms import model_registry  # noqa: F401
from sqlalchemy import text
from hrms.core.database import AsyncSessionLocal
from hrms.modules.people.router import apply_due_actions


async def main():
    async with AsyncSessionLocal() as session:
        tenants = list((await session.execute(text("SELECT id FROM tenants WHERE status = 'ACTIVE' AND archived_at IS NULL"))).scalars())
    for tenant_id in tenants:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})
                await apply_due_actions(session, tenant_id)


if __name__ == "__main__":
    asyncio.run(main())

"""Scheduled jobs (hrms.jobs): accrual as the system, idempotence, tenant isolation, metrics."""

import pytest
from sqlalchemy import text

from hrms.core.authz import SYSTEM_ACTOR
from hrms.core.ids import to_uuid
from hrms.jobs import runner
from tests.helpers import employee, ok, tenant

pytestmark = pytest.mark.database


async def _accruals(engine, tid, eid):
    async with engine.begin() as conn:
        rows = await conn.execute(
            text("""
                SELECT recorded_by, quantity FROM leave_balance_transactions
                WHERE tenant_id = :t AND employment_id = :e AND transaction_type = 'ACCRUAL'
            """),
            {"t": tid, "e": eid},
        )
        return rows.all()


async def _last_run(engine, job):
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text("SELECT * FROM job_runs WHERE job = :j ORDER BY started_at DESC LIMIT 1"),
                {"j": job},
            )
        ).mappings().one()


async def test_daily_accrual_credits_everyone_once_as_the_system(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    emp, _ = await employee(client, company)
    tid, eid = to_uuid(admin["user"]["tenant_id"]), to_uuid(emp["id"])
    await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Annual", "code": "AL", "days_per_year": 12, "accrual_enabled": True},
    )

    assert await runner.run_job("accrual")
    first = await _accruals(engine, tid, eid)
    assert [(r.recorded_by, r.quantity) for r in first] == [(SYSTEM_ACTOR, 1.0)]

    # Every day it runs again; the month is only ever credited once.
    assert await runner.run_job("accrual")
    assert len(await _accruals(engine, tid, eid)) == 1

    run = await _last_run(engine, "accrual")
    assert run["status"] == "SUCCEEDED" and run["tenants_failed"] == 0 and run["finished_at"]

    metrics = (await client.get("/metrics")).text
    assert 'hrms_job_last_success_timestamp_seconds{job_name="accrual"}' in metrics


async def test_one_failing_tenant_does_not_stop_the_others(api, monkeypatch):
    client, engine = api
    admin = await tenant(client)
    broken = to_uuid(admin["user"]["tenant_id"])
    seen = []

    async def flaky(session, tenant_id):
        if tenant_id == broken:
            raise RuntimeError("boom")
        seen.append(tenant_id)
        return "fine"

    monkeypatch.setitem(runner.JOBS, "flaky", flaky)
    assert await runner.run_job("flaky") is False

    run = await _last_run(engine, "flaky")
    assert run["status"] == "FAILED" and run["tenants_failed"] == 1
    assert run["tenants_ok"] == len(seen) > 0  # the test database holds other tenants too
    assert str(broken) in run["detail"] and "RuntimeError" in run["detail"]
    assert "boom" not in run["detail"]  # error class only: messages can carry personal data

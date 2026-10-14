"""
DB-1 (docs/database-hardening-plan.md): rules the database now enforces, tested through the API
and, where the API would stop a request first, directly against the database.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from hrms.core.ids import to_uuid
from tests.helpers import PASSWORD, employee, make_user, ok, sign_in, tenant

pytestmark = pytest.mark.database

SYSTEM = "00000000-0000-0000-0000-000000000000"


async def _system_account(engine, tenant_id):
    async with engine.connect() as conn:
        return (
            (
                await conn.execute(
                    text(
                        "SELECT status, email, password_hash, employment_id FROM user_accounts "
                        "WHERE tenant_id = :t AND id = :s"
                    ),
                    {"t": tenant_id, "s": SYSTEM},
                )
            )
            .mappings()
            .first()
        )


# ── W2.1 System account ──────────────────────────────────────────────────────────────────────


async def test_every_tenant_has_a_system_account_that_cannot_sign_in(api):
    client, engine = api
    admin = await tenant(client)
    account = await _system_account(engine, to_uuid(admin["user"]["tenant_id"]))
    assert dict(account) == {
        "status": "SYSTEM",
        "email": None,
        "password_hash": None,
        "employment_id": None,
    }
    users = await ok(client, "GET", "/v1/users")
    assert users and all(u["status"] != "SYSTEM" for u in users)
    for identifier in ("System", SYSTEM, "SYSTEM"):
        assert (await sign_in(client, identifier, PASSWORD)).status_code in (401, 422)


async def test_a_tenant_created_outside_the_app_gets_one_too(api):
    _, engine = api
    tenant_id = uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO tenants (id, slug, display_name, status, plan) "
                "VALUES (:id, :slug, 'Raw insert', 'ACTIVE', 'STARTER')"
            ),
            {"id": tenant_id, "slug": "raw-" + tenant_id.hex[:12]},
        )
    assert (await _system_account(engine, tenant_id))["status"] == "SYSTEM"


# ── W2.2 One login per employee ──────────────────────────────────────────────────────────────


async def test_an_employee_has_at_most_one_login(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    emp, _ = await employee(client, company)
    second = await client.post(
        "/v1/users",
        json={
            "email": uuid4().hex + "@example.com",
            "password": PASSWORD,
            "role": "EMPLOYEE",
            "scope_type": "SELF",
            "employment_id": emp["id"],
        },
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "This employee already has a login"
    # The database holds the rule even for a writer that skips the API's check.
    async with engine.connect() as conn:
        with pytest.raises(IntegrityError, match="uq_user_accounts_employment"):
            await conn.execute(
                text(
                    "INSERT INTO user_accounts (tenant_id, id, employment_id) "
                    "VALUES (:t, gen_random_uuid(), :e)"
                ),
                {"t": to_uuid(admin["user"]["tenant_id"]), "e": to_uuid(emp["id"])},
            )


# ── W2.7 Email ───────────────────────────────────────────────────────────────────────────────


async def test_a_login_email_is_unique_across_tenants_with_a_clear_message(api):
    client, _ = api
    await tenant(client)
    email, _, _ = await make_user(client, role="HR_MANAGER", scope_type="ALL")
    await tenant(client)
    clash = await client.post(
        "/v1/users",
        json={
            "email": email.upper(),
            "password": PASSWORD,
            "role": "HR_MANAGER",
            "scope_type": "ALL",
        },
    )
    assert clash.status_code == 409
    assert clash.json()["detail"] == "A user with this email already exists"


# ── Clear messages ───────────────────────────────────────────────────────────────────────────


async def test_every_constraint_message_names_a_real_constraint(api):
    from hrms.core.error_handlers import CONSTRAINT_MESSAGES

    _, engine = api
    async with engine.connect() as conn:
        names = set(
            (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE connamespace = 'public'::regnamespace "
                        "UNION SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
                    )
                )
            ).scalars()
        )
    assert sorted(set(CONSTRAINT_MESSAGES) - names) == []


# ── W5.3 Platform tables ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("table", ["platform_admins", "platform_password_reset_tokens"])
async def test_tenant_requests_cannot_reach_platform_tables(table):
    import os

    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    url = make_url(os.environ["HRMS_TEST_DATABASE_URL"])
    app = create_async_engine(
        url.set(username="hrms_app", password="hrms_app_dev_password"), poolclass=NullPool
    )
    try:
        async with app.connect() as conn:
            with pytest.raises(DBAPIError, match="permission denied"):
                await conn.execute(text(f"SELECT count(*) FROM {table}"))
    finally:
        await app.dispose()


# ── W6 Optimistic locking ────────────────────────────────────────────────────────────────────


async def test_a_stale_edit_is_refused_instead_of_overwriting(api):
    client, _ = api
    await tenant(client)
    job = await ok(client, "POST", "/v1/org/jobs", json={"title": "Analyst", "code": "AN1"})
    loaded = job["version"]
    first = await ok(
        client, "PATCH", f"/v1/org/jobs/{job['id']}", json={"title": "Senior", "version": loaded}
    )
    assert first["version"] == loaded + 1
    # A second editor still holding the old version is told, not silently overwritten.
    stale = await client.patch(
        f"/v1/org/jobs/{job['id']}", json={"title": "Junior", "version": loaded}
    )
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_VERSION"
    # Without a version (older clients), the edit still applies.
    assert (
        await ok(client, "PATCH", f"/v1/org/jobs/{job['id']}", json={"title": "Lead"})
    )["title"] == "Lead"


# ── W7 Change history ────────────────────────────────────────────────────────────────────────


async def test_changes_are_recorded_for_every_write_path_with_the_actor(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    actor = to_uuid(admin["user"]["id"])
    lt = await ok(
        client, "POST", "/v1/leave/types", json={"name": "Study", "code": "STU", "days_per_year": 5}
    )
    await ok(client, "PATCH", f"/v1/leave/types/{lt['id']}", json={"days_per_year": 6})
    # A write that bypasses the API (an import, a fix by hand) is recorded too, as System.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE leave_types SET name = 'Exam' WHERE tenant_id = :t AND id = :i"),
            {"t": tid, "i": to_uuid(lt["id"])},
        )
        rows = (
            await conn.execute(
                text(
                    "SELECT action, changes, changed_by FROM entity_change_log "
                    "WHERE tenant_id = :t AND entity_type = 'leave_type' AND entity_id = :i "
                    "ORDER BY changed_at, action"
                ),
                {"t": tid, "i": to_uuid(lt["id"])},
            )
        ).all()
    assert [r.action for r in rows] == ["CREATE", "UPDATE", "UPDATE"]
    assert rows[1].changes == {"days_per_year": {"old": 5, "new": 6}}
    assert rows[1].changed_by == actor
    assert rows[2].changes == {"name": {"old": "Study", "new": "Exam"}}
    assert str(rows[2].changed_by) == SYSTEM
    assert all("version" not in r.changes for r in rows)


async def test_access_grants_and_revocations_are_recorded(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    await make_user(client, role="HR_MANAGER", scope_type="ALL")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM role_assignments WHERE tenant_id = :t "
                "AND role_id = (SELECT id FROM roles WHERE tenant_id = :t AND name = 'HR_MANAGER')"
            ),
            {"t": tid},
        )
        actions = (
            await conn.execute(
                text(
                    "SELECT action FROM entity_change_log WHERE tenant_id = :t "
                    "AND entity_type = 'role_assignment' ORDER BY changed_at"
                ),
                {"t": tid},
            )
        ).scalars().all()
    assert "CREATE" in actions and actions[-1] == "DELETE"


# ── W2.6 One grant per role and scope ────────────────────────────────────────────────────────


async def test_a_role_is_granted_once_per_scope(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company = to_uuid(admin["user"]["legal_entities"][0]["id"])
    _, _, user = await make_user(client, role="HR_MANAGER", scope_type="ALL")
    insert = text(
        "INSERT INTO role_assignments (tenant_id, id, user_account_id, role_id, scope_type, "
        "scope_value) SELECT :t, gen_random_uuid(), :u, id, :scope, :value FROM roles "
        "WHERE tenant_id = :t AND name = 'HR_MANAGER'"
    )
    async with engine.connect() as conn:
        with pytest.raises(IntegrityError, match="uq_role_assignments_grant"):
            await conn.execute(
                insert, {"t": tid, "u": to_uuid(user["id"]), "scope": "ALL", "value": None}
            )
    # The same role with a different scope is a different grant.
    async with engine.begin() as conn:
        await conn.execute(
            insert,
            {"t": tid, "u": to_uuid(user["id"]), "scope": "LEGAL_ENTITY", "value": str(company)},
        )


# ── W7.3 Nightly integrity checks ────────────────────────────────────────────────────────────


async def test_integrity_checks_find_dangling_references_and_excuse_removals(api):
    from hrms.core import database
    from hrms.db.integrity import run_checks

    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])

    async def findings():
        async with database.AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)}
            )
            return await run_checks(session)

    assert set((await findings()).values()) == {0}
    gone, removed = uuid4(), uuid4()
    async with engine.begin() as conn:
        for entity, action in ((gone, "UPDATE"), (removed, "UPDATE"), (removed, "DELETE")):
            await conn.execute(
                text(
                    "INSERT INTO entity_change_log (tenant_id, id, entity_type, entity_id, "
                    "action, changes, changed_by, changed_at) VALUES (:t, gen_random_uuid(), "
                    "'leave_type', :e, :a, '{}', :s, now())"
                ),
                {"t": tid, "e": entity, "a": action, "s": SYSTEM},
            )
    found = await findings()
    assert found["change_log_target_missing"] == 1  # `removed` has its DELETE entry
    assert sum(found.values()) == 1


async def test_the_integrity_job_reports_to_metrics(api, monkeypatch):
    from unittest.mock import AsyncMock

    from hrms.jobs import runner

    client, engine = api
    admin = await tenant(client)
    # Just this test's tenant: the shared test database holds every other test's tenants too.
    monkeypatch.setattr(
        runner, "_active_tenants", AsyncMock(return_value=[to_uuid(admin["user"]["tenant_id"])])
    )
    assert await runner._run_job("integrity")
    async with engine.connect() as conn:
        findings = await conn.scalar(
            text(
                "SELECT findings FROM job_runs WHERE job = 'integrity' "
                "ORDER BY started_at DESC LIMIT 1"
            )
        )
    assert "change_log_target_missing" in findings
    exported = (await client.get("/metrics")).text
    for metric in (
        "hrms_integrity_violations{check=",
        "hrms_db_size_bytes",
        "hrms_db_table_size_bytes{table=\"punches\"}",
        "hrms_db_table_seq_rows_read_total",
        "hrms_db_oldest_transaction_seconds",
    ):
        assert metric in exported, metric

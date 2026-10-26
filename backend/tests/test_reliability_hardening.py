"""Regression tests for failures reproduced in the stability audit."""

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from hrms.core import database
from hrms.core.config import settings
from hrms.jobs.runner import _periods
from tests.helpers import ok
from tests.test_platform_console import _console


@pytest.mark.parametrize("failure", ["pg_dump", "pg_restore", "tar", "psql", None])
def test_backup_daemon_never_advances_success_after_failure(tmp_path, failure):
    commands = tmp_path / "bin"
    commands.mkdir()
    store = tmp_path / "documents"
    store.mkdir()
    (store / "scan").write_bytes(b"scan")
    for name in ("pg_dump", "pg_restore", "tar", "psql", "sleep"):
        script = commands / name
        if name == failure or name == "sleep":
            body = "exit 1"
        elif name == "pg_dump":
            body = (
                'for arg in "$@"; do case "$arg" in --file=*) '
                'echo dump > "${arg#--file=}";; esac; done'
            )
        elif name == "psql":
            body = 'sh "$BACKUP_SCRIPT" --locked'
        elif name == "tar":
            body = 'if [ "$1" = "-czf" ]; then echo archive > "$2"; fi'
        else:
            body = "exit 0"
        script.write_text("#!/bin/sh\n" + body + "\n")
        script.chmod(0o755)
    out = tmp_path / "backups" / "audit"
    out.mkdir(parents=True)
    (out / "latest").write_text("last-good.dump\n2000-01-01T00:00:00Z\n")
    (out / "hrms-old.dump").write_text("valid old backup")
    os.utime(out / "hrms-old.dump", (1, 1))
    env = {
        **os.environ,
        "PATH": str(commands) + ":" + os.environ["PATH"],
        "BACKUP_ROOT": str(tmp_path / "backups"),
        "KYC_ROOT": str(store),
        "HRMS_ENVIRONMENT": "audit",
    }
    result = subprocess.run(
        ["sh", str(Path(__file__).parents[2] / "deploy/backup/backup.sh"), "--daemon"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if failure:
        assert (out / "latest").read_text().startswith("last-good.dump")
        assert (out / "hrms-old.dump").exists()
        assert "backup ok" not in result.stdout
        assert "backup FAILED" in result.stderr
    else:
        dump = out / (out / "latest").read_text().splitlines()[0]
        assert dump.exists() and Path(str(dump) + ".sha256").exists()
        assert "backup ok" in result.stdout


def test_job_periods_catch_up_across_year_boundary():
    assert _periods("2025-12", "2026-02") == ["2025-12", "2026-01", "2026-02"]
    with pytest.raises(ValueError):
        _periods("2026-13", "2027-01")
    with pytest.raises(ValueError):
        _periods("2027-01", "2026-12")


@pytest.mark.database
async def test_platform_reset_revokes_existing_token_and_link(api, monkeypatch):
    client, engine = api
    email, old = await _console(client, engine)
    monkeypatch.setattr(settings, "debug", True)
    link = await ok(client, "POST", "/v1/platform/forgot-password", json={"email": email})
    token = link["dev_reset_url"].split("token=")[1]
    sibling = await ok(client, "POST", "/v1/platform/forgot-password", json={"email": email})
    sibling_token = sibling["dev_reset_url"].split("token=")[1]
    body = {"token": token, "new_password": "New-password-6543"}
    await ok(client, "POST", "/v1/platform/reset-password", json=body)
    assert (await client.get("/v1/platform/me", headers=old)).status_code == 401
    assert (await client.post("/v1/platform/reset-password", json=body)).status_code == 400
    assert (
        await client.post(
            "/v1/platform/reset-password",
            json={"token": sibling_token, "new_password": "Other-password-6543"},
        )
    ).status_code == 400


@pytest.mark.database
async def test_database_failure_inside_scheduled_actions_does_not_abort_request(api, monkeypatch):
    _, engine = api
    from hrms.modules.people import router

    async def fail(session, tenant_id):
        await session.execute(text("SELECT 1/0"))

    monkeypatch.setattr(router, "apply_due_actions", fail)
    async with database.AsyncSessionLocal() as session:
        await database._apply_scheduled_actions(session, None)
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


@pytest.mark.database
async def test_scheduler_lease_prevents_parallel_execution_and_releases_on_failure(
    api, monkeypatch
):
    import asyncio

    from hrms.jobs import runner

    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def hold(name):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(runner, "_run_job", hold)
    first = asyncio.create_task(runner.run_job("lease-regression"))
    await asyncio.wait_for(started.wait(), timeout=5)
    try:
        assert await runner.run_job("lease-regression")
        assert calls == 1
    finally:
        release.set()
        await first
    assert await runner.run_job("lease-regression")
    assert calls == 2

    async def fail(name):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(runner, "_run_job", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        await runner.run_job("lease-regression")
    monkeypatch.setattr(runner, "_run_job", hold)
    assert await runner.run_job("lease-regression")
    assert calls == 3


@pytest.mark.database
async def test_reset_outbox_retries_provider_failure_without_storing_plain_tokens(api, monkeypatch):
    import json

    from hrms.core import mail
    from hrms.core.field_crypto import cipher

    client, engine = api
    email, _ = await _console(client, engine)
    monkeypatch.setattr(settings, "mail_backend", "ses")
    monkeypatch.setattr(settings, "mail_from", "verified@example.com")
    monkeypatch.setattr(settings, "platform_reset_base_url", "https://hrms.example.com")
    monkeypatch.setattr(settings, "debug", False)
    reply = await ok(client, "POST", "/v1/platform/forgot-password", json={"email": email})
    assert not reply.get("dev_reset_url")
    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text("""SELECT t.id, t.delivery_payload FROM
            platform_password_reset_tokens t JOIN platform_admins a ON a.id=t.admin_id
            WHERE a.email=:email ORDER BY t.created_at DESC LIMIT 1"""),
                    {"email": email},
                )
            )
            .mappings()
            .one()
        )
    assert row["delivery_payload"].startswith("enc:v1:")
    assert email not in row["delivery_payload"]
    payload = json.loads(cipher().decrypt(row["delivery_payload"], mail.AAD))
    assert payload["to"] == email and "token=" in payload["url"]

    def fail(payload):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(mail, "_send", fail)
    assert await mail.deliver_pending() is False
    async with engine.begin() as conn:
        assert (
            await conn.execute(
                text("SELECT delivery_attempts FROM platform_password_reset_tokens WHERE id=:id"),
                {"id": row["id"]},
            )
        ).scalar() == 1
        await conn.execute(
            text("UPDATE platform_password_reset_tokens SET delivery_next_at=NULL WHERE id=:id"),
            {"id": row["id"]},
        )
    sent = []
    monkeypatch.setattr(mail, "_send", sent.append)
    assert await mail.deliver_pending()
    assert sent == [payload]
    async with engine.begin() as conn:
        final = (
            await conn.execute(
                text(
                    "SELECT delivery_payload, delivered_at FROM "
                    "platform_password_reset_tokens WHERE id=:id"
                ),
                {"id": row["id"]},
            )
        ).one()
    assert final.delivery_payload is None and final.delivered_at is not None
    assert await mail.deliver_pending()
    assert len(sent) == 1


@pytest.mark.database
async def test_unconfigured_recovery_returns_the_same_error_for_known_and_unknown_accounts(
    api, monkeypatch
):
    # Pin the settings: a developer's .env with HRMS_DEBUG=true turns recovery on.
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "mail_backend", "disabled")
    client, engine = api
    email, _ = await _console(client, engine)
    known = await client.post("/v1/platform/forgot-password", json={"email": email})
    unknown = await client.post(
        "/v1/platform/forgot-password", json={"email": "unknown@example.com"}
    )
    assert known.status_code == unknown.status_code == 503
    assert known.json()["detail"] == unknown.json()["detail"]
    assert known.json()["error"]["code"] == unknown.json()["error"]["code"]


@pytest.mark.database
async def test_account_and_analysis_pages_are_bounded_without_losing_totals(api):
    from tests.helpers import employee, tenant

    client, _ = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    for _ in range(3):
        await employee(client, company)
    all_users = await ok(client, "GET", "/v1/users")
    pages = [
        await ok(client, "GET", f"/v1/users?limit=1&offset={i}") for i in range(len(all_users))
    ]
    assert [page[0]["id"] for page in pages] == [row["id"] for row in all_users]
    assert (await client.get("/v1/users?limit=201")).status_code == 422
    analysis = await ok(client, "GET", "/v1/time/daily-analysis?limit=1")
    assert len(analysis["employees"]) <= 1
    assert analysis["total_filtered"] == 3
    assert (await client.get("/v1/time/daily-analysis?limit=501")).status_code == 422


@pytest.mark.database
async def test_bulk_ledger_gate_blocks_writers_and_does_not_survive_transaction_boundaries(api):
    from uuid import uuid4

    from hrms.modules.leave.engine import lock_bulk_ledger, lock_leave_bucket

    tid, emp, bucket = uuid4(), uuid4(), uuid4()
    key = f"{tid}:leave-ledger"
    async with database.AsyncSessionLocal() as bulk, database.AsyncSessionLocal() as other:
        await lock_bulk_ledger(bulk, tid)
        acquired = (
            await other.execute(
                text("SELECT pg_try_advisory_xact_lock_shared(hashtextextended(:key,0))"),
                {"key": key},
            )
        ).scalar()
        assert acquired is False
        await other.rollback()
        await bulk.rollback()
        await lock_leave_bucket(bulk, tid, emp, bucket)
        assert (
            await other.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
            )
        ).scalar() is False
        await bulk.rollback()
        await other.rollback()
        async with bulk.begin_nested() as nested:
            await lock_bulk_ledger(bulk, tid)
            await nested.rollback()
        await lock_leave_bucket(bulk, tid, emp, bucket)
        assert (
            await other.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
            )
        ).scalar() is False


@pytest.mark.database
async def test_scoped_account_pagination_handles_malformed_legacy_scope(api):
    from hrms.core.ids import to_uuid
    from tests.helpers import PASSWORD, bearer, employee, make_user, tenant

    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    _, first = await employee(client, company)
    _, malformed = await employee(client, company)
    email, _, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company]
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE role_assignments SET scope_type='LEGAL_ENTITY', "
                "scope_value='invalid JSON' WHERE user_account_id=:id"
            ),
            {"id": to_uuid(malformed["user"]["id"])},
        )
    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": PASSWORD}
    )
    headers = bearer(login["access_token"])
    rows = await ok(client, "GET", "/v1/users?limit=200", headers=headers)
    assert first["user"]["id"] in {r["id"] for r in rows}
    assert admin["user"]["id"] not in {r["id"] for r in rows}
    assert malformed["user"]["id"] not in {r["id"] for r in rows}
    pages = [
        await ok(client, "GET", f"/v1/users?limit=1&offset={i}", headers=headers)
        for i in range(len(rows))
    ]
    assert [p[0]["id"] for p in pages] == [r["id"] for r in rows]


@pytest.mark.database
async def test_encryption_check_detects_wrong_key_material_under_the_active_key_id(
    api, monkeypatch
):
    import base64

    from hrms.core.field_crypto import DEV_KEY_ID
    from hrms.deploy import UnreadableValues, _rewrite_pii
    from tests.test_kyc_privacy import _setup

    client, _ = api
    await _setup(client)  # KYC identifiers written with the test key (id "dev")
    await _rewrite_pii(check=True)  # the right key: every value decrypts

    wrong = DEV_KEY_ID + ":" + base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "field_encryption_keys", wrong)
    with pytest.raises(UnreadableValues, match="employee_kyc_records"):
        await _rewrite_pii(check=True)

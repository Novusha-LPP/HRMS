"""Regression coverage for the review's remaining failures, on synthetic data only."""

import base64
import time
from uuid import UUID

import pytest
from sqlalchemy import text

from hrms.core.config import settings
from hrms.core.document_store import MAGIC, sealed_key_id, unseal
from hrms.core.field_crypto import DEV_KEYS, PREFIX, FieldCipher, FieldCryptoError
from hrms.core.mfa import matching_step, totp
from tests.helpers import PASSWORD, bearer, ok, person_and_employment, tenant
from tests.test_platform import _platform_admin


@pytest.mark.parametrize("token", ["A", "!!", "", "AA"])
def test_malformed_field_ciphertext_uses_crypto_error(token):
    cipher = FieldCipher(DEV_KEYS)
    with pytest.raises(FieldCryptoError):
        cipher.decrypt(PREFIX + cipher.active_id + ":" + token, "pan_number")


@pytest.mark.parametrize(
    "blob", [MAGIC, MAGIC + b"\x00", MAGIC + b"\x01x", MAGIC + b"\x01\xff" + bytes(28)]
)
def test_truncated_document_envelopes_use_crypto_error(blob):
    for operation in (sealed_key_id, lambda value: unseal(value, "document")):
        with pytest.raises(FieldCryptoError):
            operation(blob)


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_rfc6238_sha1_vectors(timestamp, expected):
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp(secret, timestamp // 30, digits=8) == expected


def test_totp_replay_and_window():
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    code = totp(secret, 100)
    assert matching_step(secret, code, now=3000) == 100
    assert matching_step(secret, code, 100, now=3000) is None
    assert matching_step(secret, code, now=3090) is None
    assert matching_step(secret, "１２３４５６", now=3000) is None


@pytest.mark.database
async def test_browser_cookie_csrf_logout_and_no_token_body(api):
    client, _ = api
    registered = await tenant(client)
    old = bearer(registered["access_token"])
    email = registered["user"]["email"]
    client.headers.clear()
    headers = {"X-HRMS-Session": "cookie", "Origin": "http://localhost:5173"}
    result = await client.post(
        "/v1/auth/login", headers=headers, json={"identifier": email, "password": PASSWORD}
    )
    assert result.status_code == 200, result.text
    assert result.json()["access_token"] == ""
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert (await client.get("/v1/auth/me")).status_code == 200
    for unsafe in [
        {},
        {"X-HRMS-Session": "cookie"},
        {"X-HRMS-Session": "cookie", "Origin": "https://attacker.example"},
    ]:
        assert (await client.post("/v1/auth/logout", headers=unsafe, json={})).status_code == 403
    assert (await client.post("/v1/auth/logout", headers=headers, json={})).status_code == 204
    assert (await client.get("/v1/auth/me", headers=old)).status_code == 401
    assert (await client.get("/v1/auth/me")).status_code == 401


@pytest.mark.database
@pytest.mark.parametrize("platform", [False, True])
async def test_enrollment_gating_login_replay_and_revocation(api, monkeypatch, platform):
    client, engine = api
    if platform:
        email = await _platform_admin(engine)
        base = "/v1/platform"
        login_body = {"email": email, "password": PASSWORD}
        old = bearer((await ok(client, "POST", base + "/login", json=login_body))["access_token"])
        protected = base + "/tenants"
    else:
        data = await tenant(client)
        base = "/v1/auth"
        email = data["user"]["email"]
        login_body = {"identifier": email, "password": PASSWORD}
        old = bearer(data["access_token"])
        protected = "/v1/users"
    client.headers.clear()
    monkeypatch.setattr(settings, "privileged_mfa_required", True)
    assert (await client.get(protected, headers=old)).status_code == 403
    assert (await client.get(base + "/me", headers=old)).json()["mfa_required"] is True
    bad = await client.post(base + "/mfa/enroll", headers=old, json={"password": "wrong"})
    assert bad.status_code == 400
    setup = await ok(client, "POST", base + "/mfa/enroll", headers=old, json={"password": PASSWORD})
    secret = setup["secret"]
    current = int(time.time() // 30)
    await ok(
        client, "POST", base + "/mfa/confirm", headers=old, json={"code": totp(secret, current)}
    )
    assert (await client.get(base + "/me", headers=old)).status_code == 401
    response = await client.post(base + "/login", json=login_body)
    assert response.status_code == 401 and response.json()["code"] == "MFA_REQUIRED"
    replay = await client.post(base + "/login", json={**login_body, "otp": totp(secret, current)})
    assert replay.status_code == 401
    # The accepted +1 drift step avoids a real sleep, while exercising the same path.
    login = await ok(
        client, "POST", base + "/login", json={**login_body, "otp": totp(secret, current + 1)}
    )
    new = bearer(login["access_token"])
    assert (await client.get(protected, headers=new)).status_code == 200
    assert (await client.get(base + "/me", headers=new)).json()["mfa_required"] is False
    assert (
        await client.post(base + "/login", json={**login_body, "otp": totp(secret, current + 1)})
    ).status_code == 401
    async with engine.connect() as conn:
        table = "platform_admins" if platform else "user_accounts"
        stored = (
            await conn.execute(
                text(f"SELECT mfa_secret,mfa_pending_secret FROM {table} WHERE email=:email"),
                {"email": email},
            )
        ).one()
        assert stored.mfa_secret.startswith(PREFIX) and secret not in stored.mfa_secret
        assert stored.mfa_pending_secret is None


@pytest.mark.database
async def test_report_snapshot_is_reused_scoped_and_csv_safe(api, monkeypatch):
    from hrms.modules.time import router

    client, engine = api
    first = await tenant(client)
    le = first["user"]["legal_entities"][0]["id"]
    for name in ["=1+1", "Beta", "Gamma"]:
        await person_and_employment(client, le, legal_first_name=name)
    report = await ok(client, "GET", "/v1/time/daily-analysis?limit=1&work_date=2026-10-05")
    assert report["total_filtered"] == 3 and len(report["employees"]) == 1
    sid = report["snapshot_id"]

    async def forbidden(*args, **kwargs):
        raise AssertionError("Paging/export must not recompute source attendance")

    monkeypatch.setattr(router, "_daily_batch", forbidden)
    page = await ok(
        client,
        "GET",
        f"/v1/time/daily-analysis?limit=1&offset=1&work_date=2026-10-05&snapshot_id={sid}",
    )
    assert page["employees"][0]["employment_id"] != report["employees"][0]["employment_id"]
    exported = await client.get(
        f"/v1/time/daily-analysis/export?work_date=2026-10-05&snapshot_id={sid}"
    )
    assert exported.status_code == 200 and "'=1+1" in exported.text
    await tenant(client)
    assert (
        await client.get(f"/v1/time/daily-analysis?work_date=2026-10-05&snapshot_id={sid}")
    ).status_code == 409
    client.headers.update(bearer(first["access_token"]))
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE daily_report_snapshots SET expires_at=now()-interval '1 second' "
                "WHERE id=CAST(:id AS uuid)"
            ),
            {"id": sid},
        )
    assert (
        await client.get(f"/v1/time/daily-analysis?work_date=2026-10-05&snapshot_id={sid}")
    ).status_code == 409


def test_deployed_cookie_is_secure_host_only_and_private(monkeypatch):
    from fastapi import Request, Response

    from hrms.core.browser_sessions import issue_browser_session

    monkeypatch.setattr(settings, "environment", "production")
    request = Request({"type": "http", "headers": [(b"x-hrms-session", b"cookie")]})
    response = Response()
    assert issue_browser_session(request, response, "synthetic-token", 60) == ""
    cookie = response.headers["set-cookie"]
    assert "__Host-hrms_session=" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("spec", ["x:" + "!" * 44, "x" * 256 + ":" + "A" * 43])
def test_invalid_key_encoding_or_envelope_id_is_rejected(spec):
    with pytest.raises(FieldCryptoError):
        FieldCipher(spec)


@pytest.mark.database
async def test_mfa_seeds_rotate_and_malformed_seed_is_audited(api, monkeypatch):
    from hrms.core.field_crypto import cipher
    from hrms.core.ids import to_uuid
    from hrms.deploy import _rewrite_mfa_seeds

    client, engine = api
    data = await tenant(client)
    tid, uid = to_uuid(data["user"]["tenant_id"]), to_uuid(data["user"]["id"])
    seed = base64.b32encode(b"synthetic-factor-key").decode().rstrip("=")
    stored = cipher().encrypt(seed, "mfa_secret")
    new = "rotated:" + base64.urlsafe_b64encode(bytes(range(32))).decode()
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE user_accounts SET mfa_secret=:seed,mfa_pending_secret=:seed WHERE id=:id"),
            {"seed": stored, "id": uid},
        )
    monkeypatch.setattr(settings, "field_encryption_keys", new + "," + DEV_KEYS)
    errors = []
    try:
        assert await _rewrite_mfa_seeds(engine, [tid], check=True, errors=errors) >= 2
        assert not errors
        await _rewrite_mfa_seeds(engine, [tid], check=False, errors=errors)
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT mfa_secret,mfa_pending_secret FROM user_accounts WHERE id=:id"),
                    {"id": uid},
                )
            ).one()
            for value in row:
                assert value.startswith("enc:v1:rotated:")
                assert cipher().decrypt(value, "mfa_secret") == seed
            await conn.execute(
                text(
                    "UPDATE user_accounts SET mfa_pending_secret='enc:v1:rotated:!!' WHERE id=:id"
                ),
                {"id": uid},
            )
        errors.clear()
        await _rewrite_mfa_seeds(engine, [tid], check=True, errors=errors)
        assert errors == [f"user_accounts.mfa_pending_secret id={uid}"]
        assert seed not in " ".join(errors)
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE user_accounts SET mfa_pending_secret=NULL WHERE id=:id"), {"id": uid}
            )
        monkeypatch.setattr(settings, "field_encryption_keys", DEV_KEYS + "," + new)
        await _rewrite_mfa_seeds(engine, [tid], check=False, errors=[])


@pytest.mark.database
async def test_daily_job_reclaims_expired_report_rows_only_for_its_tenant(api):
    from hrms.core import database
    from hrms.core.ids import to_uuid
    from hrms.jobs.runner import _scheduled_actions

    client, engine = api
    first = await tenant(client)
    await person_and_employment(client, first["user"]["legal_entities"][0]["id"])
    one = await ok(client, "GET", "/v1/time/daily-analysis")
    await tenant(client)
    two = await ok(client, "GET", "/v1/time/daily-analysis")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE daily_report_snapshots SET expires_at=now()-interval '1 second' "
                "WHERE id IN (CAST(:one AS uuid),CAST(:two AS uuid))"
            ),
            {"one": one["snapshot_id"], "two": two["snapshot_id"]},
        )
    tid = to_uuid(first["user"]["tenant_id"])
    async with database.AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id',:tid,true)"), {"tid": str(tid)}
        )
        await _scheduled_actions(session, tid)
    async with engine.connect() as conn:
        remaining = (
            (
                await conn.execute(
                    text(
                        "SELECT id FROM daily_report_snapshots WHERE id IN "
                        "(CAST(:one AS uuid),CAST(:two AS uuid))"
                    ),
                    {"one": one["snapshot_id"], "two": two["snapshot_id"]},
                )
            )
            .scalars()
            .all()
        )
        assert remaining == [UUID(two["snapshot_id"])]
        assert (
            await conn.execute(
                text("SELECT count(*) FROM daily_report_rows WHERE snapshot_id=CAST(:id AS uuid)"),
                {"id": one["snapshot_id"]},
            )
        ).scalar_one() == 0

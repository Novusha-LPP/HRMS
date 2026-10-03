"""The platform console: sign-in hardening, role enforcement, and its cross-tenant reads."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.config import settings
from hrms.core.security import hash_password
from tests.helpers import PASSWORD, bearer, client_from, ok, tenant

pytestmark = pytest.mark.database


async def _platform_admin(engine, role="ADMIN", status="ACTIVE"):
    email = f"platform-{uuid4().hex[:8]}@example.com"
    async with engine.begin() as conn:
        await conn.execute(
            text("""INSERT INTO platform_admins (id, email, name, password_hash, role, status)
                    VALUES (:i, :e, 'Test Admin', :p, :r, :s)"""),
            {"i": uuid4(), "e": email, "p": hash_password(PASSWORD), "r": role, "s": status},
        )
    return email


async def _sign_in(client, email, password=PASSWORD):
    return await client.post("/v1/platform/login", json={"email": email, "password": password})


async def test_platform_sign_in_and_role_enforcement(api):
    client, engine = api
    admin_email = await _platform_admin(engine, "ADMIN")
    viewer_email = await _platform_admin(engine, "VIEWER")
    await _platform_admin(engine, "ADMIN", status="SUSPENDED")
    suspended = await _platform_admin(engine, "ADMIN", status="SUSPENDED")

    admin = bearer(
        (
            await ok(
                client,
                "POST",
                "/v1/platform/login",
                json={"email": admin_email, "password": PASSWORD},
            )
        )["access_token"]
    )
    viewer = bearer(
        (
            await ok(
                client,
                "POST",
                "/v1/platform/login",
                json={"email": viewer_email, "password": PASSWORD},
            )
        )["access_token"]
    )
    assert (await _sign_in(client, suspended)).status_code == 401
    assert (await _sign_in(client, "nobody@example.com")).status_code == 401
    assert (await _sign_in(client, admin_email, "wrong-password-1")).status_code == 401

    me = await ok(client, "GET", "/v1/platform/me", headers=admin)
    assert me["role"] == "ADMIN" and me["email"] == admin_email

    # Every read works for both roles; every write is admin-only.
    await tenant(client)  # give the platform something to list
    for path in ("/v1/platform/tenants", "/v1/platform/admins", "/v1/platform/audit-log"):
        for who in (admin, viewer):
            assert (await client.get(path, headers=who)).status_code == 200, path
    listing = await ok(client, "GET", "/v1/platform/tenants", headers=admin)
    first = (
        listing["tenants"][0]
        if isinstance(listing, dict) and "tenants" in listing
        else listing["items"][0]
    )
    detail = await client.get(f"/v1/platform/tenants/{first['id']}", headers=viewer)
    assert detail.status_code == 200
    patch = await client.patch(
        f"/v1/platform/tenants/{first['id']}", headers=viewer, json={"plan": "PRO"}
    )
    assert patch.status_code == 403
    add = await client.post(
        "/v1/platform/admins",
        headers=viewer,
        json={"email": "new@example.com", "name": "New", "password": PASSWORD, "role": "ADMIN"},
    )
    assert add.status_code == 403
    # A tenant token is never a platform token, and vice versa.
    assert (
        await client.get(
            "/v1/platform/me", headers={"Authorization": client.headers["Authorization"]}
        )
    ).status_code == 401
    assert (await client.get("/v1/employees", headers=admin)).status_code == 401


async def test_platform_sign_in_is_throttled_and_does_not_share_counters_with_tenants(api):
    client, engine = api
    email = await _platform_admin(engine)
    async with client_from("10.55.0.1") as attacker:
        for _ in range(settings.login_max_failures):
            assert (await _sign_in(attacker, email, "wrong-password-1")).status_code == 401
        locked = await _sign_in(attacker, email, PASSWORD)
        assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    async with client_from("10.55.0.2") as elsewhere:
        assert (await _sign_in(elsewhere, email)).status_code == 200
    # Tenant sign-in from the locked address is untouched: separate realm.
    admin = await tenant(client)
    async with client_from("10.55.0.1") as same_ip:
        r = await same_ip.post(
            "/v1/auth/login", json={"identifier": admin["user"]["email"], "password": PASSWORD}
        )
        assert r.status_code == 200


async def test_forgot_password_is_rate_limited_and_never_reveals_accounts(api, monkeypatch):
    client, engine = api
    from hrms.core.config import settings

    # Exercise the enabled delivery path without calling a provider (outbox only).
    monkeypatch.setattr(settings, "mail_backend", "ses")
    monkeypatch.setattr(settings, "platform_reset_base_url", "https://hrms.example.com")
    known = await _platform_admin(engine)
    async with client_from("10.66.0.1") as anon:
        replies = set()
        for who in (known, "ghost@example.com"):
            r = await anon.post("/v1/platform/forgot-password", json={"email": who})
            assert r.status_code == 200
            replies.add(r.json()["message"])
        assert len(replies) == 1  # identical for existing and unknown addresses
        assert "dev_reset_url" not in r.json() or r.json()["dev_reset_url"] is None  # debug is off
        for _ in range(8):
            await anon.post("/v1/platform/forgot-password", json={"email": "ghost@example.com"})
        assert (
            await anon.post("/v1/platform/forgot-password", json={"email": known})
        ).status_code == 429

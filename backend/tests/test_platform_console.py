"""
The platform console's write paths: registering companies, suspending/archiving/restoring
tenants (and what that does to their users), managing platform admins, password resets.
"""

from uuid import uuid4

import pytest

from hrms.core.config import settings
from tests.helpers import PASSWORD, bearer, ok
from tests.test_platform import _platform_admin, _sign_in

pytestmark = pytest.mark.database


async def _console(client, engine, role="ADMIN"):
    email = await _platform_admin(engine, role=role)
    r = await _sign_in(client, email)
    assert r.status_code == 200, r.text
    return email, bearer(r.json()["access_token"])


async def _new_tenant(client, admin):
    email = f"{uuid4().hex[:10]}@example.com"
    company = await ok(
        client, "POST", "/v1/platform/companies", headers=admin,
        json={"company_name": f"Acme {uuid4().hex[:6]}", "mode": "NEW_TENANT",
              "admin_email": email, "admin_password": PASSWORD},
    )
    return company, email


async def _tenant_login(client, email):
    return await client.post("/v1/auth/login", json={"identifier": email, "password": PASSWORD})


async def test_new_tenant_and_subsidiary(api):
    client, engine = api
    _, admin = await _console(client, engine)
    company, email = await _new_tenant(client, admin)
    assert company["mode"] == "NEW_TENANT" and company["admin_email"] == email
    assert (await _tenant_login(client, email)).status_code == 200

    sub = await ok(
        client, "POST", "/v1/platform/companies", headers=admin,
        json={"company_name": "Acme Exports", "mode": "SUBSIDIARY",
              "parent_tenant_id": company["tenant_id"]},
    )
    assert sub["tenant_id"] == company["tenant_id"]
    assert sub["legal_entity_id"] != company["legal_entity_id"]

    # Each mode needs its own fields.
    for body in (
        {"company_name": "No admin", "mode": "NEW_TENANT"},
        {"company_name": "No parent", "mode": "SUBSIDIARY"},
    ):
        r = await client.post("/v1/platform/companies", headers=admin, json=body)
        assert r.status_code in (400, 422), body


async def test_suspend_archive_and_restore_a_tenant(api):
    client, engine = api
    _, admin = await _console(client, engine)
    company, email = await _new_tenant(client, admin)
    tid = company["tenant_id"]
    session = bearer((await _tenant_login(client, email)).json()["access_token"])
    assert (await client.get("/v1/auth/me", headers=session)).status_code == 200

    # Suspending cuts off already-issued sessions on their next request, and new sign-ins.
    await ok(client, "PATCH", f"/v1/platform/tenants/{tid}", headers=admin,
             json={"status": "SUSPENDED"})
    assert (await client.get("/v1/leave/types", headers=session)).status_code == 403
    assert (await _tenant_login(client, email)).status_code in (401, 403)
    await ok(client, "PATCH", f"/v1/platform/tenants/{tid}", headers=admin,
             json={"status": "ACTIVE", "plan": "ENTERPRISE"})
    assert (await _tenant_login(client, email)).status_code == 200

    # Archive (soft delete) hides it from the console list; restore brings it back.
    await ok(client, "POST", f"/v1/platform/tenants/{tid}/archive", headers=admin)
    assert (await _tenant_login(client, email)).status_code in (401, 403)
    listed = await ok(client, "GET", "/v1/platform/tenants", headers=admin)
    rows = listed["items"] if isinstance(listed, dict) else listed
    archived = next((t for t in rows if t["id"] == tid), None)
    assert archived is None or archived.get("archived_at")
    await ok(client, "POST", f"/v1/platform/tenants/{tid}/restore", headers=admin)
    assert (await _tenant_login(client, email)).status_code == 200


async def test_viewers_cannot_change_anything(api):
    client, engine = api
    _, admin = await _console(client, engine)
    company, _ = await _new_tenant(client, admin)
    _, viewer = await _console(client, engine, role="VIEWER")
    for method, path, body in (
        ("PATCH", f"/v1/platform/tenants/{company['tenant_id']}", {"status": "SUSPENDED"}),
        ("POST", f"/v1/platform/tenants/{company['tenant_id']}/archive", None),
        ("POST", "/v1/platform/admins", {"name": "X Y", "email": "x@example.com",
                                         "password": PASSWORD}),
        ("POST", "/v1/platform/companies", {"company_name": "Nope", "mode": "NEW_TENANT",
                                            "admin_email": "n@example.com",
                                            "admin_password": PASSWORD}),
    ):
        r = await client.request(method, path, headers=viewer, json=body)
        assert r.status_code == 403, (method, path)


async def test_admins_can_be_added_suspended_and_cannot_lock_themselves_out(api):
    client, engine = api
    me_email, admin = await _console(client, engine)
    email = f"ops-{uuid4().hex[:8]}@example.com"
    created = await ok(client, "POST", "/v1/platform/admins", headers=admin,
                       json={"name": "Ops Person", "email": email, "password": PASSWORD})
    assert created["role"] == "ADMIN" and created["status"] == "ACTIVE"
    assert (await _sign_in(client, email)).status_code == 200

    await ok(client, "PATCH", f"/v1/platform/admins/{created['id']}", headers=admin,
             json={"status": "SUSPENDED"})
    assert (await _sign_in(client, email)).status_code in (401, 403)
    demoted = await ok(client, "PATCH", f"/v1/platform/admins/{created['id']}", headers=admin,
                       json={"status": "ACTIVE", "role": "VIEWER"})
    assert demoted["role"] == "VIEWER"

    # Your own account can't be suspended or demoted from here.
    admins = await ok(client, "GET", "/v1/platform/admins", headers=admin)
    me = next(a for a in admins if a["is_you"])
    assert me["email"] == me_email
    for body in ({"status": "SUSPENDED"}, {"role": "VIEWER"}):
        r = await client.patch(f"/v1/platform/admins/{me['id']}", headers=admin, json=body)
        assert r.status_code in (400, 403, 409), body

    duplicate = await client.post("/v1/platform/admins", headers=admin,
                                  json={"name": "Dup", "email": email, "password": PASSWORD})
    assert duplicate.status_code in (400, 409)


async def test_password_reset_with_the_emailed_link(api, monkeypatch):
    client, engine = api
    email, _ = await _console(client, engine)
    # No email provider is wired up: the link is only returned in debug (local) mode.
    monkeypatch.setattr(settings, "debug", True)
    sent = await ok(client, "POST", "/v1/platform/forgot-password", json={"email": email})
    token = next(v for k, v in sent.items() if k != "message" and v)
    token = token.rsplit("token=", 1)[-1] if "token=" in str(token) else token

    new_password = "N3w-" + uuid4().hex
    await ok(client, "POST", "/v1/platform/reset-password",
             json={"token": token, "new_password": new_password})
    assert (await _sign_in(client, email, new_password)).status_code == 200
    assert (await _sign_in(client, email)).status_code == 401
    # A link works once.
    again = await client.post("/v1/platform/reset-password",
                              json={"token": token, "new_password": "Other-" + uuid4().hex})
    assert again.status_code in (400, 401, 410)

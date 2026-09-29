"""KYC identity/bank numbers are masked for roles that don't need them, and access is logged."""

import pytest
from sqlalchemy import text

from hrms.modules.kyc.router import mask_identifier
from tests.helpers import bearer, hire, make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

KYC = {
    "pan_number": "ABCDE1234F",
    "aadhaar_number": "123456789012",
    "account_number": "00112233445566",
    "bank_name": "Test Bank",
    "ifsc_code": "TEST0000001",
    "current_address": "1 Test Road",
}


def test_mask_identifier_keeps_only_the_tail():
    assert mask_identifier("ABCDE1234F") == "••••••234F"
    assert mask_identifier("123456789012") == "••••••••9012"
    assert mask_identifier("12") == "••"  # too short to reveal any of it
    assert mask_identifier(None) is None and mask_identifier("") == ""


async def _login(client, email, password):
    r = await ok(client, "POST", "/v1/auth/login", json={"identifier": email, "password": password})
    return bearer(r["access_token"])


async def _setup(client):
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    subject = await person_and_employment(client, le)
    await hire(client, subject["id"], placement)
    boss = await person_and_employment(client, le)
    await hire(client, boss["id"], placement)
    own = await make_user(client, subject["id"])
    mgr = await make_user(
        client, boss["id"], role="MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    acct = await make_user(
        client, role="ACCOUNTANT", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    tokens = {
        "self": await _login(client, own[0], own[1]),
        "manager": await _login(client, mgr[0], mgr[1]),
        "accountant": await _login(client, acct[0], acct[1]),
    }
    await ok(client, "PATCH", "/v1/kyc/me", headers=tokens["self"], json=KYC)
    return subject, tokens


async def test_identity_numbers_are_masked_unless_you_are_hr_or_the_owner(api):
    client, _ = api
    subject, tokens = await _setup(client)

    own = await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"])
    assert own["pan_number"] == "ABCDE1234F" and own["aadhaar_number"] == "123456789012"

    hr = await ok(client, "GET", f"/v1/kyc/employees/{subject['id']}")  # the SUPER_ADMIN
    assert hr["pan_number"] == "ABCDE1234F" and hr["account_number"] == "00112233445566"

    for role in ("manager", "accountant"):
        seen = await ok(client, "GET", f"/v1/kyc/employees/{subject['id']}", headers=tokens[role])
        assert seen["pan_number"] == "••••••234F", role
        assert seen["aadhaar_number"] == "••••••••9012", role
        assert seen["account_number"] == "••••••••••5566", role
        # Status-level information is what kyc.read is for, and stays visible.
        assert (
            seen["bank_name"] == "Test Bank" and seen["status"] and "completion_percentage" in seen
        )


async def test_raw_documents_need_hr_level_access_and_every_view_is_logged(api):
    client, _ = api
    subject, tokens = await _setup(client)
    doc = await ok(
        client,
        "POST",
        "/v1/kyc/me/documents",
        headers=tokens["self"],
        files={"file": ("pan.pdf", b"%PDF-1.4 fake pan card scan", "application/pdf")},
        data={"document_type": "PAN_CARD", "document_title": "PAN card"},
    )
    url = f"/v1/kyc/documents/{doc['id']}/download"

    assert (await client.get(url, headers=tokens["manager"])).status_code == 403
    assert (await client.get(url, headers=tokens["accountant"])).status_code == 403
    assert (await client.get(url, headers=tokens["self"])).status_code == 200  # your own scan
    hr_download = await client.get(url)
    assert hr_download.status_code == 200 and hr_download.content.startswith(b"%PDF-")

    # Managers can open the masked dossier, so they show up in the log; the owner doesn't.
    await ok(client, "GET", f"/v1/kyc/employees/{subject['id']}", headers=tokens["manager"])
    await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"])

    log = await ok(client, "GET", f"/v1/kyc/employees/{subject['id']}/access-log")
    actions = sorted((e["action"], e["unmasked"]) for e in log)
    assert actions == [("DOWNLOAD_DOCUMENT", True), ("VIEW_DOSSIER", False)]
    assert (
        await client.get(f"/v1/kyc/employees/{subject['id']}/access-log", headers=tokens["manager"])
    ).status_code == 403  # the log itself is HR-only


async def test_the_access_log_is_append_only_for_the_application(api):
    client, engine = api
    subject, tokens = await _setup(client)
    await ok(client, "GET", f"/v1/kyc/employees/{subject['id']}", headers=tokens["manager"])
    import os

    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    app_url = make_url(os.environ["HRMS_TEST_DATABASE_URL"]).set(
        username="hrms_app", password="hrms_app_dev_password"
    )
    runtime = create_async_engine(app_url, poolclass=NullPool)
    async with runtime.connect() as conn:
        for statement in (
            "DELETE FROM kyc_access_log",
            "UPDATE kyc_access_log SET unmasked = false",
        ):
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(text(statement))
            await conn.rollback()
    await runtime.dispose()

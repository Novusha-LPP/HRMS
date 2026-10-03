"""KYC from submission to verification: documents, HR edits, deletion rules, the HR list."""

import pytest

from tests.helpers import ok
from tests.test_kyc_privacy import _setup

pytestmark = pytest.mark.database

PDF = b"%PDF-1.4 a scan"


async def _upload(client, headers=None, path="/v1/kyc/me/documents", kind="PAN_CARD"):
    kw = {"headers": headers} if headers else {}
    return await ok(
        client, "POST", path, **kw,
        files={"file": ("scan.pdf", PDF, "application/pdf")},
        data={"document_type": kind, "document_title": kind.replace("_", " ").title()},
    )


async def test_submit_review_and_verify(api):
    client, _ = api
    subject, tokens = await _setup(client)
    doc = await _upload(client, tokens["self"])

    submitted = await ok(client, "POST", "/v1/kyc/me/submit", headers=tokens["self"])
    assert submitted["status"] == "SUBMITTED"

    # A document can be rejected with a reason, then verified; the reason goes away.
    url = f"/v1/kyc/documents/{doc['id']}/verify"
    rejected = await ok(client, "PATCH", url,
                        json={"status": "REJECTED", "rejection_reason": "Blurry"})
    assert rejected["status"] == "REJECTED" and rejected["rejection_reason"] == "Blurry"
    verified = await ok(client, "PATCH", url, json={"status": "VERIFIED", "comments": "OK"})
    assert verified["status"] == "VERIFIED" and verified["rejection_reason"] is None
    bad = await client.patch(url, json={"status": "MAYBE"})
    assert bad.status_code == 400

    overall = await ok(client, "POST", f"/v1/kyc/employees/{subject['id']}/verify",
                       json={"status": "VERIFIED"})
    assert overall["status"] == "VERIFIED" and overall["verified_at"]

    # Managers and accountants can't verify anything.
    for role in ("manager", "accountant"):
        r = await client.patch(url, headers=tokens[role], json={"status": "VERIFIED"})
        assert r.status_code == 403, role


async def test_a_verified_document_cannot_be_deleted_by_its_owner(api):
    client, _ = api
    _, tokens = await _setup(client)
    keep = await _upload(client, tokens["self"])
    scrap = await _upload(client, tokens["self"], kind="BANK_PROOF")
    await ok(client, "PATCH", f"/v1/kyc/documents/{keep['id']}/verify",
             json={"status": "VERIFIED"})

    blocked = await client.delete(f"/v1/kyc/documents/{keep['id']}", headers=tokens["self"])
    assert blocked.status_code == 400
    assert (await client.delete(f"/v1/kyc/documents/{scrap['id']}",
                                headers=tokens["self"])).status_code == 204
    gone = await client.get(f"/v1/kyc/documents/{scrap['id']}/download", headers=tokens["self"])
    assert gone.status_code == 404
    # HR may remove even a verified one; a manager may not.
    assert (await client.delete(f"/v1/kyc/documents/{keep['id']}",
                                headers=tokens["manager"])).status_code == 403
    assert (await client.delete(f"/v1/kyc/documents/{keep['id']}")).status_code == 204


async def test_hr_edits_and_uploads_for_an_employee(api):
    client, _ = api
    subject, tokens = await _setup(client)
    edited = await ok(client, "PATCH", f"/v1/kyc/employees/{subject['id']}",
                      json={"uan_number": "100200300400", "blood_group": "O+"})
    assert edited["uan_number"] == "100200300400" and edited["blood_group"] == "O+"
    # The employee sees HR's edit.
    own = await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"])
    assert own["uan_number"] == "100200300400"

    doc = await _upload(client, path=f"/v1/kyc/employees/{subject['id']}/documents",
                        kind="AADHAAR_FRONT")
    download = await client.get(f"/v1/kyc/documents/{doc['id']}/download", headers=tokens["self"])
    assert download.status_code == 200 and download.content == PDF
    # A manager may read the masked dossier but not edit it.
    r = await client.patch(f"/v1/kyc/employees/{subject['id']}", headers=tokens["manager"],
                           json={"blood_group": "A+"})
    assert r.status_code == 403


async def test_the_hr_list_and_summary_count_the_employee(api):
    client, _ = api
    subject, _ = await _setup(client)
    listed = await ok(client, "GET", "/v1/kyc/employees")
    items = listed["items"] if isinstance(listed, dict) else listed
    assert subject["id"] in {i["employment_id"] for i in items}
    before = await ok(client, "GET", "/v1/kyc/summary")
    assert before["total_employees"] >= 1 and before["verified_count"] == 0
    await ok(client, "POST", f"/v1/kyc/employees/{subject['id']}/verify",
             json={"status": "VERIFIED"})
    after = await ok(client, "GET", "/v1/kyc/summary")
    assert after["verified_count"] == before["verified_count"] + 1
    assert after["total_employees"] == before["total_employees"]


async def test_uploads_reject_what_is_not_a_document(api):
    client, _ = api
    _, tokens = await _setup(client)
    exe = await client.post(
        "/v1/kyc/me/documents", headers=tokens["self"],
        files={"file": ("x.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
        data={"document_type": "PAN_CARD", "document_title": "PAN"},
    )
    assert exe.status_code == 415
    long_number = await client.post(
        "/v1/kyc/me/documents", headers=tokens["self"],
        files={"file": ("x.pdf", PDF, "application/pdf")},
        data={"document_type": "PAN_CARD", "document_title": "PAN", "document_number": "9" * 101},
    )
    assert long_number.status_code == 422

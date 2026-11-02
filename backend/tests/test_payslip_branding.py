"""
Payslip branding over HTTP: company details, the group default with per-company overrides,
logo and signature uploads, signatories, payslip templates and the SAMPLE preview — and who
may see or change each of them.
"""

import io

import pytest
from PIL import Image

from tests.helpers import bearer, make_user, ok, person_and_employment, tenant

pytestmark = pytest.mark.database


def _png(width=400, height=120):
    out = io.BytesIO()
    Image.new("RGBA", (width, height), (15, 118, 110, 255)).save(out, "PNG")
    return out.getvalue()


async def _login(client, email, password):
    result = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    return bearer(result["access_token"])


async def _user(client, role, companies=None, employment_id=None):
    scope = {"scope_type": "LEGAL_ENTITY", "legal_entity_ids": companies} if companies else {}
    email, password, _ = await make_user(client, employment_id, role=role, **scope)
    return await _login(client, email, password)


async def _companies(client):
    first = (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"]
    second = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Second Co"})
    return first, second["id"]


async def _upload(client, kind="LOGO", content=None, headers=None, name="logo.png"):
    return await client.post(
        "/v1/branding/assets",
        data={"kind": kind},
        files={"file": (name, content or _png(), "image/png")},
        headers=headers or {},
    )


async def test_company_details_are_cleaned_checked_and_audited(api):
    client, _ = api
    await tenant(client)
    le, _ = await _companies(client)
    saved = await ok(
        client,
        "PATCH",
        f"/v1/org/legal-entities/{le}",
        json={
            "registered_name": "Acme Logistics Private Limited",
            "address_line1": "Plot 12, MIDC",
            "city": "Mumbai",
            "state_code": "mh",
            "pincode": "400093",
            "pan": "aaaca 1234a",
            "cin": "U63090MH2015PTC123456",
            "pf_establishment_code": "MHBAN0012345000",
            "esic_employer_code": "31000123450000999",
        },
    )
    assert saved["pan"] == "AAACA1234A" and saved["state_code"] == "MH"
    assert saved["esic_employer_code"] == "31000123450000999"
    for field, bad in (("pan", "ABC12"), ("gstin", "27AAACA1234A"), ("tan", "1234567890")):
        response = await client.patch(f"/v1/org/legal-entities/{le}", json={field: bad})
        assert response.status_code == 422, field
    history = await ok(client, "GET", f"/v1/org/legal-entities/{le}/history")
    assert history[0]["changes"]["pan"]["new"] == "AAACA1234A"


async def test_companies_inherit_the_group_field_by_field(api):
    client, _ = api
    await tenant(client)
    le, other = await _companies(client)
    logo = (await _upload(client)).json()
    group = await ok(
        client,
        "PUT",
        "/v1/branding/profiles/group",
        json={
            "logo_asset_id": logo["id"],
            "primary_color": "#1d4ed8",
            "footer_text": "Registered office: Mumbai",
        },
    )
    assert group["primary_color"] == "#1D4ED8" and group["logo"]["id"] == logo["id"]
    own = await ok(
        client,
        "PUT",
        f"/v1/branding/profiles/companies/{le}",
        json={"primary_color": "#B91C1C", "contact_email": "payroll@acme.example"},
    )

    mine = await ok(client, "GET", "/v1/branding/resolved", params={"legal_entity_id": le})
    sources = {k: (v["value"], v["source"]) for k, v in mine["fields"].items()}
    assert sources["primary_color"] == ("#B91C1C", "COMPANY")
    assert sources["footer_text"] == ("Registered office: Mumbai", "GROUP")
    assert sources["logo_asset_id"] == (logo["id"], "GROUP")
    assert sources["accent_color"][1] == "DEFAULT"
    assert mine["logo"]["id"] == logo["id"] and mine["company"]["name"]

    theirs = await ok(client, "GET", "/v1/branding/resolved", params={"legal_entity_id": other})
    assert theirs["fields"]["primary_color"] == {"value": "#1D4ED8", "source": "GROUP"}

    # Someone else saved in between: a stale version is refused, not overwritten.
    await ok(
        client, "PUT", f"/v1/branding/profiles/companies/{le}", json={"version": own["version"]}
    )
    stale = await client.put(
        f"/v1/branding/profiles/companies/{le}", json={"version": own["version"]}
    )
    assert stale.status_code == 409

    await ok(client, "DELETE", f"/v1/branding/profiles/companies/{le}")
    back = await ok(client, "GET", "/v1/branding/resolved", params={"legal_entity_id": le})
    assert back["fields"]["primary_color"]["source"] == "GROUP"
    profiles = await ok(client, "GET", "/v1/branding/profiles")
    assert [p["legal_entity_id"] for p in profiles] == [None]


async def test_a_light_brand_colour_is_darkened_for_text(api):
    client, _ = api
    await tenant(client)
    await ok(client, "PUT", "/v1/branding/profiles/group", json={"primary_color": "#FACC15"})
    group = await ok(client, "GET", "/v1/branding/resolved")
    assert group["color_check"]["adjusted"] is True
    assert group["color_check"]["contrast"] >= 4.5


async def test_uploads_are_checked_and_never_duplicated(api):
    client, _ = api
    await tenant(client)
    first = await _upload(client)
    assert first.status_code == 201
    again = await _upload(client)
    assert again.json()["id"] == first.json()["id"]  # same picture, same asset

    not_image = await _upload(client, content=b"hello", name="x.txt")
    assert not_image.status_code == 422
    tiny = await _upload(client, content=_png(80, 30))
    assert tiny.status_code == 422 and "too small" in tiny.json()["detail"]

    image = await client.get(f"/v1/branding/assets/{first.json()['id']}/image")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"

    # A logo can't stand in for a signature, or the other way round.
    signature = (await _upload(client, kind="SIGNATURE", content=_png(300, 90))).json()
    wrong = await client.put("/v1/branding/profiles/group", json={"logo_asset_id": signature["id"]})
    assert wrong.status_code == 422


async def test_company_hr_changes_only_their_company(api):
    client, _ = api
    await tenant(client)
    le, other = await _companies(client)
    await ok(
        client, "PUT", f"/v1/branding/profiles/companies/{other}", json={"website": "b.example"}
    )
    hr = await _user(client, "HR_MANAGER", [le])

    mine = await client.put(
        f"/v1/branding/profiles/companies/{le}", json={"primary_color": "#000000"}, headers=hr
    )
    assert mine.status_code == 200
    for path in ("/v1/branding/profiles/group", f"/v1/branding/profiles/companies/{other}"):
        response = await client.put(path, json={"primary_color": "#000000"}, headers=hr)
        assert response.status_code == 403, path
    visible = await ok(client, "GET", "/v1/branding/profiles", headers=hr)
    assert [p["legal_entity_id"] for p in visible] == [le]
    hidden = await client.get(
        "/v1/branding/resolved", params={"legal_entity_id": other}, headers=hr
    )
    assert hidden.status_code == 403


async def test_signatures_are_shown_only_to_who_manages_them(api):
    client, _ = api
    await tenant(client)
    le, _ = await _companies(client)
    logo = (await _upload(client)).json()
    signature = (await _upload(client, kind="SIGNATURE", content=_png(300, 90))).json()
    payroll = await _user(client, "PAYROLL_ADMIN", [le])
    emp = await person_and_employment(client, le)
    employee = await _user(client, "EMPLOYEE", employment_id=emp["id"])

    assert (await client.get(f"/v1/branding/assets/{logo['id']}/image", headers=payroll)).is_success
    for headers in (payroll, employee):
        response = await client.get(f"/v1/branding/assets/{signature['id']}/image", headers=headers)
        assert response.status_code == 403
    assert (
        await client.get(f"/v1/branding/assets/{logo['id']}/image", headers=employee)
    ).status_code == 403
    upload = await _upload(client, headers=payroll)
    assert upload.status_code == 403


async def test_signatories_and_templates(api):
    client, _ = api
    await tenant(client)
    le, other = await _companies(client)
    signature = (await _upload(client, kind="SIGNATURE", content=_png(300, 90))).json()
    group_signer = await ok(
        client,
        "POST",
        "/v1/branding/signatories",
        json={
            "name": "Priya Nair",
            "designation": "Head of HR",
            "signature_asset_id": signature["id"],
        },
    )
    company_signer = await ok(
        client,
        "POST",
        "/v1/branding/signatories",
        json={"name": "Ravi Kumar", "legal_entity_id": le},
    )
    assert group_signer["signature"]["id"] == signature["id"]

    overview = await ok(client, "GET", "/v1/payroll/payslip-templates")
    assert overview["group"]["id"] is None and overview["group"]["layout"] == "MODERN"
    assert {c["legal_entity_id"] for c in overview["companies"]} == {le, other}
    assert all(c["template"] is None for c in overview["companies"])
    assert "bank_account" in {f["key"] for f in overview["fields"]}

    # A company's own signatory can't sign every company's payslips.
    body = {
        "layout": "CLASSIC",
        "signature_mode": "SIGNATORY",
        "signatory_id": company_signer["id"],
    }
    wrong = await client.put("/v1/payroll/payslip-templates/group", json=body)
    assert wrong.status_code == 422
    group = await ok(
        client,
        "PUT",
        "/v1/payroll/payslip-templates/group",
        json=body | {"signatory_id": group_signer["id"]},
    )
    assert group["layout"] == "CLASSIC" and group["version"] == 0
    company = await ok(client, "PUT", f"/v1/payroll/payslip-templates/companies/{le}", json=body)
    assert company["legal_entity_id"] == le

    in_use = await client.post(f"/v1/branding/signatories/{group_signer['id']}/archive")
    assert in_use.status_code == 409
    for bad in (
        {"signature_mode": "SIGNATORY"},
        {"employee_fields": ["salary"]},
        {"employee_fields": ["pan", "pan"]},
        {"layout": "FANCY"},
    ):
        response = await client.put("/v1/payroll/payslip-templates/group", json=bad)
        assert response.status_code == 422, bad

    await ok(client, "DELETE", f"/v1/payroll/payslip-templates/companies/{le}")
    overview = await ok(client, "GET", "/v1/payroll/payslip-templates")
    assert overview["group"]["layout"] == "CLASSIC"
    assert all(c["template"] is None for c in overview["companies"])
    await ok(client, "POST", f"/v1/branding/signatories/{company_signer['id']}/archive")
    names = [s["name"] for s in await ok(client, "GET", "/v1/branding/signatories")]
    assert names == ["Priya Nair"]


async def test_preview_is_a_sample_pdf_for_payroll_and_hr_only(api):
    client, _ = api
    await tenant(client)
    le, other = await _companies(client)
    logo = (await _upload(client)).json()
    await ok(
        client, "PUT", f"/v1/branding/profiles/companies/{le}", json={"logo_asset_id": logo["id"]}
    )
    body = {"legal_entity_id": le, "template": {"layout": "COMPACT"}}

    pdf = await client.post("/v1/payroll/payslip-templates/preview", json=body)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "no-store"
    group = await client.post("/v1/payroll/payslip-templates/preview", json={"template": {}})
    assert group.status_code == 200
    image = await client.post(
        "/v1/payroll/payslip-templates/preview", params={"format": "png"}, json=body
    )
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")

    payroll = await _user(client, "PAYROLL_ADMIN", [le])
    hr = await _user(client, "HR_MANAGER", [le])
    for headers in (payroll, hr):
        assert (
            await client.post("/v1/payroll/payslip-templates/preview", json=body, headers=headers)
        ).status_code == 200
        elsewhere = await client.post(
            "/v1/payroll/payslip-templates/preview",
            json=body | {"legal_entity_id": other},
            headers=headers,
        )
        assert elsewhere.status_code == 403
        group_save = await client.put(
            "/v1/payroll/payslip-templates/group", json={}, headers=headers
        )
        assert group_save.status_code == 403

    approver = await _user(client, "PAYROLL_APPROVER", [le])
    denied = await client.post("/v1/payroll/payslip-templates/preview", json=body, headers=approver)
    assert denied.status_code == 403

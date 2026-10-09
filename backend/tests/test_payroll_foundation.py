"""
Payroll foundation over HTTP: statutory values are data with a source and a second person's
verification, salary structures are versioned, and employee salaries are effective-dated with
full history. Only the payroll roles (and the Admin) can see any of it, within their companies.
"""

from datetime import date, timedelta

import pytest

from tests.helpers import bearer, make_user, ok, person_and_employment, tenant

pytestmark = pytest.mark.database


async def _login(client, email, password):
    result = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    return bearer(result["access_token"])


async def _payroll_user(client, role, le, employment_id=None):
    email, password, _ = await make_user(
        client, employment_id, role=role, scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    return await _login(client, email, password)


async def _company(client):
    return (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"]


async def _setup(client):
    """Defaults loaded, the standard structure created; returns (company, structure)."""
    await ok(client, "POST", "/v1/payroll/statutory-rules/india-defaults")
    structure = await ok(client, "POST", "/v1/payroll/structures/standard")
    return await _company(client), structure


async def test_statutory_defaults_load_unverified_and_need_a_second_person(api):
    client, _ = api
    await tenant(client)
    le = await _company(client)
    rules = await ok(client, "POST", "/v1/payroll/statutory-rules/india-defaults")
    assert len(rules) == 9 and not any(r["verified"] for r in rules)
    again = await ok(client, "POST", "/v1/payroll/statutory-rules/india-defaults")
    assert len(again) == 9  # never duplicated or overwritten

    ceiling = next(r for r in rules if r["rule_code"] == "PF_WAGE_CEILING")
    me = await ok(client, "GET", "/v1/auth/me")
    assert ceiling["recorded_by_id"] == me["id"]  # lets the page hide Verify for its author
    own = await client.post(f"/v1/payroll/statutory-rules/{ceiling['id']}/verify")
    assert own.status_code == 403  # the person who entered it can't verify it

    reviewer = await _payroll_user(client, "PAYROLL_REVIEWER", le)
    verified = await ok(
        client, "POST", f"/v1/payroll/statutory-rules/{ceiling['id']}/verify", headers=reviewer
    )
    assert verified["verified"] is True and verified["verified_by_name"]

    # The reviewer can't change values, only check them.
    write = await client.post(
        "/v1/payroll/statutory-rules",
        json={
            "rule_code": "PF_WAGE_CEILING",
            "value": "25000",
            "effective_from": "2027-04-01",
            "source": "x" * 5,
        },
        headers=reviewer,
    )
    assert write.status_code == 403


async def test_a_new_statutory_value_ends_the_old_one(api):
    client, _ = api
    await tenant(client)
    await ok(client, "POST", "/v1/payroll/statutory-rules/india-defaults")
    body = {
        "rule_code": "ESIC_WAGE_CEILING",
        "value": "25000",
        "effective_from": "2027-04-01",
        "source": "Notification (test)",
    }
    new = await ok(client, "POST", "/v1/payroll/statutory-rules", json=body)
    assert new["verified"] is False and new["effective_to"] is None
    rows = [
        r
        for r in await ok(client, "GET", "/v1/payroll/statutory-rules")
        if r["rule_code"] == "ESIC_WAGE_CEILING"
    ]
    old = next(r for r in rows if r["id"] != new["id"])
    assert old["effective_to"] == "2027-04-01"

    earlier = await client.post(
        "/v1/payroll/statutory-rules", json=body | {"effective_from": "2027-01-01"}
    )
    assert earlier.status_code == 409
    unknown = await client.post("/v1/payroll/statutory-rules", json=body | {"rule_code": "NOPE"})
    assert unknown.status_code == 422


async def test_standard_structure_breaks_a_ctc_down(api):
    client, _ = api
    await tenant(client)
    _, structure = await _setup(client)
    assert [ln["component_code"] for ln in structure["lines"]] == [
        "BASIC",
        "HRA",
        "SPECIAL",
        "PF_ER",
        "ESIC_ER",
        "PF_EE",
        "ESIC_EE",
    ]
    lines = [
        {k: ln[k] for k in ("component_id", "calc_type", "percent", "base", "base_component_id")}
        for ln in structure["lines"]
    ]
    breakup = await ok(
        client,
        "POST",
        "/v1/payroll/structures/preview",
        json={"annual_ctc": "600000", "lines": lines},
    )
    amounts = {ln["code"]: ln["monthly"] for ln in breakup["lines"]}
    assert (amounts["BASIC"], amounts["PF_ER"], amounts["SPECIAL"]) == (
        "25000.00",
        "1800",
        "13200.00",
    )
    assert breakup["net_before_tax"] == "46400.00"
    assert breakup["provisional"] is True  # nobody has verified the defaults yet

    two_balances = lines + [{**lines[2]}]
    bad = await client.post(
        "/v1/payroll/structures",
        json={
            "name": "Broken",
            "lines": [lines[0], lines[2], {**lines[1], "calc_type": "BALANCE"}],
        },
    )
    assert bad.status_code == 422
    dup = await client.post("/v1/payroll/structures", json={"name": "Dup", "lines": two_balances})
    assert dup.status_code == 422


async def test_components_are_unique_and_statutory_ones_have_the_right_kind(api):
    client, _ = api
    await tenant(client)
    await ok(client, "POST", "/v1/payroll/components/standard")
    clash = await client.post(
        "/v1/payroll/components", json={"code": "basic", "name": "Basic again", "kind": "EARNING"}
    )
    assert clash.status_code == 409
    wrong_kind = await client.post(
        "/v1/payroll/components",
        json={"code": "PF2", "name": "PF", "kind": "EARNING", "statutory_code": "PF_EMPLOYER"},
    )
    assert wrong_kind.status_code == 422
    conv = await ok(
        client,
        "POST",
        "/v1/payroll/components",
        json={"code": "conv", "name": "Conveyance", "kind": "EARNING"},
    )
    assert conv["code"] == "CONV"
    renamed = await ok(
        client, "PATCH", f"/v1/payroll/components/{conv['id']}", json={"name": "Conveyance allw."}
    )
    assert renamed["name"] == "Conveyance allw."


async def test_salary_assignment_revision_and_history(api):
    client, _ = api
    await tenant(client)
    le, structure = await _setup(client)
    emp = await person_and_employment(client, le)
    path = f"/v1/payroll/employees/{emp['id']}/compensation"

    before_joining = await client.post(
        path,
        json={
            "structure_id": structure["id"],
            "annual_ctc": "600000",
            "effective_from": "2019-12-01",
        },
    )
    assert before_joining.status_code == 422

    await ok(
        client,
        "POST",
        path,
        json={
            "structure_id": structure["id"],
            "annual_ctc": "600000",
            "effective_from": "2020-01-01",
        },
    )
    same_day = await client.post(
        path,
        json={
            "structure_id": structure["id"],
            "annual_ctc": "700000",
            "effective_from": "2020-01-01",
        },
    )
    assert same_day.status_code == 409
    await ok(
        client,
        "POST",
        path,
        json={
            "structure_id": structure["id"],
            "annual_ctc": "720000",
            "effective_from": "2021-04-01",
            "reason": "Annual revision",
        },
    )
    detail = await ok(client, "GET", path)
    assert detail["current"]["annual_ctc"] == "720000.00"
    assert [h["annual_ctc"] for h in detail["history"]] == ["720000.00", "600000.00"]
    assert detail["history"][1]["effective_to"] == "2021-04-01"
    assert detail["breakup"]["monthly_ctc"] == "60000.00"

    listed = await ok(client, "GET", "/v1/payroll/salaries")
    row = next(r for r in listed if r["employment_id"] == emp["id"])
    assert row["annual_ctc"] == "720000.00" and row["structure_name"] == "Standard (India)"


async def test_a_salary_that_starts_later_is_listed_with_its_date(api):
    client, _ = api
    await tenant(client)
    le, structure = await _setup(client)
    emp = await person_and_employment(client, le)
    later = str(date.today() + timedelta(days=40))
    await ok(
        client,
        "POST",
        f"/v1/payroll/employees/{emp['id']}/compensation",
        json={"structure_id": structure["id"], "annual_ctc": "480000", "effective_from": later},
    )
    row = next(
        r
        for r in await ok(client, "GET", "/v1/payroll/salaries")
        if r["employment_id"] == emp["id"]
    )
    assert (row["annual_ctc"], row["effective_from"]) == ("480000.00", later)
    detail = await ok(client, "GET", f"/v1/payroll/employees/{emp['id']}/compensation")
    assert detail["current"]["effective_from"] == later and detail["breakup"] is not None


async def test_a_ctc_the_structure_cannot_pay_is_refused(api):
    client, _ = api
    await tenant(client)
    le, _ = await _setup(client)
    comps = {c["code"]: c["id"] for c in await ok(client, "GET", "/v1/payroll/components")}
    fixed = await ok(
        client,
        "POST",
        "/v1/payroll/structures",
        json={
            "name": "Fixed basic",
            "lines": [
                {"component_id": comps["BASIC"], "calc_type": "FIXED", "amount": "25000"},
                {"component_id": comps["SPECIAL"], "calc_type": "BALANCE"},
            ],
        },
    )
    emp = await person_and_employment(client, le)
    low = await client.post(
        f"/v1/payroll/employees/{emp['id']}/compensation",
        json={"structure_id": fixed["id"], "annual_ctc": "120000", "effective_from": "2020-01-01"},
    )
    assert low.status_code == 422
    assert "too low" in low.text


async def test_editing_a_structure_keeps_assigned_salaries_on_their_version(api):
    client, _ = api
    await tenant(client)
    le, v1 = await _setup(client)
    emp = await person_and_employment(client, le)
    await ok(
        client,
        "POST",
        f"/v1/payroll/employees/{emp['id']}/compensation",
        json={"structure_id": v1["id"], "annual_ctc": "600000", "effective_from": "2020-01-01"},
    )
    assert (
        next(s for s in await ok(client, "GET", "/v1/payroll/structures") if s["id"] == v1["id"])[
            "employees"
        ]
        == 1
    )

    lines = [
        {k: ln[k] for k in ("component_id", "calc_type", "percent", "base", "base_component_id")}
        for ln in v1["lines"]
    ]
    lines[0]["percent"] = "40"
    v2 = await ok(
        client,
        "PUT",
        f"/v1/payroll/structures/{v1['id']}",
        json={"name": v1["name"], "lines": lines},
    )
    assert v2["id"] != v1["id"] and v2["supersedes_id"] == v1["id"]
    listed = {s["id"] for s in await ok(client, "GET", "/v1/payroll/structures")}
    assert v1["id"] not in listed and v2["id"] in listed

    detail = await ok(client, "GET", f"/v1/payroll/employees/{emp['id']}/compensation")
    assert detail["current"]["structure_id"] == v1["id"]
    basic = next(ln for ln in detail["breakup"]["lines"] if ln["code"] == "BASIC")
    assert basic["monthly"] == "25000.00"  # still 50%, from the version they were given


async def test_payroll_is_limited_to_payroll_roles_and_their_companies(api):
    client, _ = api
    await tenant(client)
    le, structure = await _setup(client)
    other = (await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Other Co"}))["id"]
    here = await person_and_employment(client, le)
    there = await person_and_employment(client, other)

    hr_person = await person_and_employment(client, le)
    email, password, _ = await make_user(
        client, hr_person["id"], role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    hr = await _login(client, email, password)
    assert (await client.get("/v1/payroll/salaries", headers=hr)).status_code == 403

    payroll_person = await person_and_employment(client, le)
    payroll = await _payroll_user(client, "PAYROLL_ADMIN", le, payroll_person["id"])
    visible = {
        r["employment_id"] for r in await ok(client, "GET", "/v1/payroll/salaries", headers=payroll)
    }
    assert here["id"] in visible and there["id"] not in visible

    body = {"structure_id": structure["id"], "annual_ctc": "600000", "effective_from": "2020-01-01"}
    await ok(
        client,
        "POST",
        f"/v1/payroll/employees/{here['id']}/compensation",
        json=body,
        headers=payroll,
    )
    other_company = await client.post(
        f"/v1/payroll/employees/{there['id']}/compensation", json=body, headers=payroll
    )
    assert other_company.status_code == 403
    own = await client.post(
        f"/v1/payroll/employees/{payroll_person['id']}/compensation", json=body, headers=payroll
    )
    assert own.status_code == 403

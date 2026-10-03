"""Employees hired in HRMS sign in with the employee number on their employment (0033)."""

import pytest

from tests.helpers import PASSWORD, hire, make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database


async def _hired_with_login(client, le, number):
    placement = await org_basics(client, le)
    emp = await person_and_employment(client, le, number)
    await hire(client, emp["id"], placement)
    email, password, _ = await make_user(client, emp["id"])
    return emp, email, password


async def test_an_app_hired_employee_signs_in_with_their_employee_number(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    emp, _, password = await _hired_with_login(client, le, "EMP-7731")
    assert emp["employee_number"] == "EMP-7731"

    for identifier in ("EMP-7731", "emp-7731", "  EMP-7731 "):
        r = await client.post("/v1/auth/login", json={"identifier": identifier,
                                                      "password": password})
        assert r.status_code == 200, (identifier, r.text)
        assert r.json()["user"]["employment_id"] == emp["id"]
    wrong = await client.post("/v1/auth/login", json={"identifier": "EMP-7731",
                                                      "password": "not-it-at-all"})
    assert wrong.status_code == 401


async def test_the_same_number_in_two_companies_is_settled_by_the_password(api):
    client, _ = api
    admin = await tenant(client)
    first_le = admin["user"]["legal_entities"][0]["id"]
    second_le = (await ok(client, "POST", "/v1/org/legal-entities",
                          json={"name": "Second Co", "country_code": "IN"}))["id"]
    a, _, password_a = await _hired_with_login(client, first_le, "E-1")
    placement = await org_basics(client, second_le)
    b = await person_and_employment(client, second_le, "E-1")
    await hire(client, b["id"], placement)
    await make_user(client, b["id"], password=PASSWORD + "-b")

    r = await client.post("/v1/auth/login", json={"identifier": "E-1", "password": password_a})
    assert r.status_code == 200 and r.json()["user"]["employment_id"] == a["id"]
    r = await client.post("/v1/auth/login",
                          json={"identifier": "E-1", "password": PASSWORD + "-b"})
    assert r.status_code == 200 and r.json()["user"]["employment_id"] == b["id"]

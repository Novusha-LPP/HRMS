"""
The leavers and rejoiners reports: right rows, scoped to what the caller manages, CSV that a
spreadsheet cannot turn into a formula, and the metrics the lifecycle emits.
"""

import csv
import io
from datetime import date, timedelta

import pytest

from tests.helpers import hire, make_user, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

TODAY = date.today()


async def _world(client, name="Asha"):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, company)
    person = await ok(
        client, "POST", "/v1/persons", json={"legal_first_name": name, "legal_last_name": "Rao"}
    )
    emp = await ok(
        client,
        "POST",
        "/v1/employees",
        json={
            "person_id": person["id"],
            "legal_entity_id": company,
            "employee_number": "R-1",
            "hire_date": "2020-01-01",
        },
    )
    await hire(client, emp["id"], placement)
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Annual", "code": "AL", "days_per_year": 12},
    )
    await ok(
        client,
        "POST",
        "/v1/leave/balances/adjust",
        json={
            "employment_id": emp["id"],
            "leave_type_id": lt["id"],
            "quantity": 10,
            "kind": "OPENING",
            "reason": "Test balance",
            "effective_date": (TODAY - timedelta(days=60)).isoformat(),
        },
    )
    return company, placement, emp


async def _leave_and_return(client, emp, placement, rejoin=None):
    await ok(
        client,
        "POST",
        "/v1/leave/separation-rules",
        json={"on_separation": "HOLD", "hold_days": 30, "effective_from": "2020-01-01"},
    )
    sep = await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "SEPARATION",
            "effective_date": (TODAY - timedelta(days=12)).isoformat(),
            "reason_code": "RESIGNATION",
        },
    )
    assert sep.status_code == 201, sep.text
    body = {
        "employment_id": emp["id"],
        "type": "REHIRE",
        "effective_date": TODAY.isoformat(),
        "changes": placement,
    }
    if rejoin:
        body["rejoin"] = rejoin
    back = await client.post("/v1/personnel-actions", json=body)
    assert back.status_code == 201, back.text


async def test_the_rejoin_report_lists_who_came_back_and_how(api):
    client, _ = api
    _, placement, emp = await _world(client)
    await _leave_and_return(client, emp, placement, {"mode": "FRESH", "reason": "New contract"})
    report = await ok(client, "GET", "/v1/people/reports/rejoins")
    assert report["columns"][:3] == ["Employee ID", "Name", "Company"]
    (row,) = report["rows"]
    assert row[0] == "R-1" and row[1] == "Asha Rao"
    assert row[5] == 12 and row[6] == "Started fresh" and row[8] == "New contract"
    empty = await ok(
        client,
        "GET",
        f"/v1/people/reports/rejoins?from_date={TODAY - timedelta(days=400)}"
        f"&to_date={TODAY - timedelta(days=300)}",
    )
    assert empty["rows"] == []


async def test_the_settlement_report_shows_what_was_done_with_the_leave(api):
    client, _ = api
    _, placement, emp = await _world(client)
    await _leave_and_return(client, emp, placement)
    report = await ok(client, "GET", "/v1/leave/reports/separation-settlements")
    (row,) = report["rows"]
    assert row[1] == "R-1" and row[3] == "Annual" and row[4] == 10 and row[7] == 10
    assert row[8] == "Hold" and row[10] == "Restored"  # they rejoined within the hold


async def test_csv_downloads_cannot_become_spreadsheet_formulas(api):
    client, _ = api
    _, placement, emp = await _world(client, name="=HYPERLINK(1)")
    await _leave_and_return(client, emp, placement)
    response = await client.get("/v1/people/reports/rejoins?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="rejoins-')
    assert response.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][0] == "Employee ID"
    assert rows[1][1] == "'=HYPERLINK(1) Rao"  # defanged


async def test_a_manager_only_sees_their_own_people_and_an_employee_sees_none(api):
    client, _ = api
    _, placement, emp = await _world(client)
    await _leave_and_return(client, emp, placement)
    email, password, _ = await make_user(client, emp["id"])
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    for path in (
        "/v1/people/reports/rejoins",
        "/v1/people/reports/company-transfers",
        "/v1/leave/reports/separation-settlements",
    ):
        assert (await client.get(path, headers=headers)).status_code == 403, path
    # Another company's administrator sees nothing of this company's people.
    from tests.helpers import client_from

    async with client_from("203.0.113.44") as other:
        await tenant(other)
        report = await ok(other, "GET", "/v1/people/reports/rejoins")
        assert report["rows"] == []


async def test_the_lifecycle_emits_its_metrics(api):
    from prometheus_client import REGISTRY

    def count(name, **labels):
        return REGISTRY.get_sample_value(name, labels) or 0.0

    client, _ = api
    before = (
        count("hrms_rejoins_total", mode="FRESH"),
        count("hrms_leave_separation_settlements_total", action="HOLD"),
        count("hrms_hire_past_employment_refused_total"),
    )
    company, placement, emp = await _world(client)
    await _leave_and_return(client, emp, placement, {"mode": "FRESH", "reason": "New contract"})
    again = await client.post(
        "/v1/employees",
        json={
            "person_id": emp["person_id"],
            "legal_entity_id": company,
            "employee_number": "DUP-2",
            "hire_date": "2020-01-01",
        },
    )
    assert again.status_code == 409
    after = (
        count("hrms_rejoins_total", mode="FRESH"),
        count("hrms_leave_separation_settlements_total", action="HOLD"),
        count("hrms_hire_past_employment_refused_total"),
    )
    assert [a - b for a, b in zip(after, before, strict=True)] == [1, 1, 1]


async def test_the_transfer_report_lists_moves_between_companies(api):
    client, _ = api
    admin = await tenant(client)
    first = admin["user"]["legal_entities"][0]["id"]
    second = (
        await ok(
            client, "POST", "/v1/org/legal-entities", json={"name": "Sister Co", "country": "IN"}
        )
    )["id"]
    placement = await org_basics(client, second)
    placement_a = await org_basics(client, first)
    emp = await person_and_employment(client, first)
    await hire(client, emp["id"], placement_a)
    moved = await client.post(
        "/v1/people/transfers",
        json={
            "employment_id": emp["id"],
            "legal_entity_id": second,
            "effective_date": TODAY.isoformat(),
            "placement": placement,
            "employee_number": "SIS-9",
            "reason": "Group restructure",
        },
    )
    assert moved.status_code == 201, moved.text
    report = await ok(client, "GET", "/v1/people/reports/company-transfers")
    (row,) = report["rows"]
    assert row[4] == "SIS-9" and row[5] == "Sister Co" and row[6] == "Carried over"
    assert row[7] == "Group restructure"

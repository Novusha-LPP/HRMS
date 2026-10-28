"""
Service with an earlier employer: recorded per person, recognised for leave eligibility and/or
gratuity, and never overlapping time worked here or another recorded period.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from tests.helpers import hire, make_user, ok, org_basics, tenant

pytestmark = pytest.mark.database

TODAY = date.today()


async def _setup(client, hired_days_ago=10):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, company)
    person = await ok(
        client,
        "POST",
        "/v1/persons",
        json={"legal_first_name": "Asha", "legal_last_name": uuid4().hex[:6]},
    )
    joined = TODAY - timedelta(days=hired_days_ago)
    emp = await ok(
        client,
        "POST",
        "/v1/employees",
        json={
            "person_id": person["id"],
            "legal_entity_id": company,
            "employee_number": uuid4().hex[:8],
            "hire_date": joined.isoformat(),
        },
    )
    await hire(client, emp["id"], placement, when=joined)
    return company, person, emp, joined


def _body(joined, months_before_end=1, years=3, **extra):
    end = joined - timedelta(days=30 * months_before_end)
    return {
        "employer_name": "Earlier Co",
        "from_date": (end - timedelta(days=365 * years)).isoformat(),
        "to_date": end.isoformat(),
        **extra,
    }


async def test_earlier_service_is_listed_with_what_is_recognised(api):
    client, _ = api
    _, person, _, joined = await _setup(client)
    url = f"/v1/persons/{person['id']}/prior-service"
    added = await client.post(
        url, json=_body(joined, recognised_for_leave=True, recognised_for_gratuity=True)
    )
    assert added.status_code == 201, added.text
    assert added.json()["months"] >= 35 and added.json()["days"] >= 1095
    other = await client.post(
        url,
        json={
            "employer_name": "Not counted",
            "from_date": (joined - timedelta(days=2000)).isoformat(),
            "to_date": (joined - timedelta(days=1500)).isoformat(),
        },
    )
    assert other.status_code == 201, other.text
    summary = await ok(client, "GET", url)
    assert len(summary["items"]) == 2
    assert summary["recognised_leave_months"] == added.json()["months"]
    assert summary["recognised_gratuity_days"] == added.json()["days"]
    assert (await client.delete(f"{url}/{added.json()['id']}")).status_code == 204
    assert (await ok(client, "GET", url))["recognised_leave_months"] == 0


async def test_dates_must_make_sense_and_not_overlap(api):
    client, _ = api
    _, person, _, joined = await _setup(client)
    url = f"/v1/persons/{person['id']}/prior-service"
    backwards = await client.post(
        url, json={"employer_name": "X", "from_date": "2020-02-01", "to_date": "2020-01-01"}
    )
    assert backwards.status_code == 422
    future = await client.post(
        url,
        json={
            "employer_name": "X",
            "from_date": (TODAY - timedelta(days=5)).isoformat(),
            "to_date": (TODAY + timedelta(days=5)).isoformat(),
        },
    )
    assert future.status_code == 422
    here = await client.post(
        url,
        json={
            "employer_name": "X",
            "from_date": (joined - timedelta(days=100)).isoformat(),
            "to_date": (joined + timedelta(days=2)).isoformat(),
        },
    )
    assert here.status_code == 422 and "overlaps their time here" in here.json()["detail"]
    assert (await client.post(url, json=_body(joined))).status_code == 201
    again = await client.post(url, json=_body(joined))
    assert again.status_code == 409


async def test_only_hr_for_that_person_can_see_or_change_it(api):
    client, _ = api
    _, person, emp, joined = await _setup(client)
    url = f"/v1/persons/{person['id']}/prior-service"
    email, password, _ = await make_user(client, emp["id"])
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert (await client.get(url, headers=headers)).status_code == 403
    assert (await client.post(url, headers=headers, json=_body(joined))).status_code == 403

    # Another company's administrator doesn't even learn that the person exists.
    from tests.helpers import client_from

    async with client_from("203.0.113.9") as other:
        await tenant(other)
        assert (await other.get(url)).status_code == 404


async def _leave_setup(client, min_months):
    bucket = await ok(
        client,
        "POST",
        "/v1/leave/buckets",
        json={"name": "Casual", "code": "CLB", "is_unlimited": False},
    )
    leave_type = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Casual", "code": "CL", "days_per_year": 12},
    )
    await ok(
        client,
        "POST",
        "/v1/leave/bucket-mappings",
        json={"leave_type_id": leave_type["id"], "bucket_id": bucket["id"]},
    )
    pset = await ok(
        client, "POST", "/v1/leave/policy-sets", json={"name": "Default", "is_default": True}
    )
    await ok(
        client,
        "POST",
        f"/v1/leave/policy-sets/{pset['id']}/bucket-policies",
        json={
            "bucket_id": bucket["id"],
            "accrual_type": "MONTHLY_PRORATE",
            "days_per_year": 12,
            "probation_eligible": True,
            "min_service_months": min_months,
        },
    )


async def _credited(client):
    result = await ok(client, "POST", f"/v1/leave/accrual/run?period={TODAY:%Y-%m}")
    return result["balances_credited"]


async def test_recognised_service_counts_towards_the_minimum_a_leave_rule_asks_for(api):
    client, _ = api
    _, person, _, joined = await _setup(client)
    await _leave_setup(client, min_months=24)
    url = f"/v1/persons/{person['id']}/prior-service"
    # Ten days into the job: not yet eligible for a rule that asks for 24 months.
    assert await _credited(client) == 0
    # Service that is on record but not recognised for leave changes nothing.
    await ok(client, "POST", url, json=_body(joined))
    assert await _credited(client) == 0
    summary = await ok(client, "GET", url)
    await client.delete(f"{url}/{summary['items'][0]['id']}")
    # Recognised for leave, three years of it: eligible straight away.
    await ok(client, "POST", url, json=_body(joined, recognised_for_leave=True))
    assert await _credited(client) == 1

"""Onboarding: templates, cases, checklist items, who may tick what, and auto-completion."""

from datetime import date, timedelta

import pytest

from tests.helpers import bearer, employee, ok, tenant

pytestmark = pytest.mark.database

TEMPLATE = {
    "name": "Factory hire",
    "items": [
        {"title": "Sign offer", "assignee_type": "EMPLOYEE", "due_days_from_hire": 0,
         "sequence": 1},
        {"title": "Issue badge", "assignee_type": "HR", "due_days_from_hire": 2, "sequence": 2},
        {"title": "Team lunch", "assignee_type": "HR", "required": False, "sequence": 3},
    ],
}


async def _case(client, hire: date | None = None):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    emp, login = await employee(client, company)
    template = await ok(client, "POST", "/v1/onboarding/templates", json=TEMPLATE)
    case = await ok(
        client,
        "POST",
        "/v1/onboarding/cases",
        json={
            "employment_id": emp["id"],
            "template_id": template["id"],
            "hire_date": (hire or date.today()).isoformat(),
        },
    )
    return emp, bearer(login["access_token"]), case


def _item(case, title):
    return next(i for i in case["items"] if i["title"] == title)


async def test_a_case_copies_the_template_with_due_dates_from_the_hire_date(api):
    client, _ = api
    hire = date.today() - timedelta(days=10)
    _, _, case = await _case(client, hire)
    assert case["status"] == "IN_PROGRESS" and case["total_items"] == 3
    assert _item(case, "Sign offer")["due_date"] == hire.isoformat()
    assert _item(case, "Issue badge")["due_date"] == (hire + timedelta(days=2)).isoformat()

    fetched = await ok(client, "GET", f"/v1/onboarding/cases/{case['id']}")
    # Hired ten days ago: every open item is past due, optional or not.
    assert fetched["overdue_items"] == 3
    listed = await ok(client, "GET", "/v1/onboarding/cases")
    assert case["id"] in {c["id"] for c in listed}


async def test_without_a_template_the_tenant_default_is_seeded_once(api):
    client, _ = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    first, _ = await employee(client, company)
    second, _ = await employee(client, company)
    a = await ok(client, "POST", "/v1/onboarding/cases",
                 json={"employment_id": first["id"], "hire_date": date.today().isoformat()})
    b = await ok(client, "POST", "/v1/onboarding/cases",
                 json={"employment_id": second["id"], "hire_date": date.today().isoformat()})
    assert a["total_items"] > 0 and a["template_id"] == b["template_id"]
    defaults = [t for t in await ok(client, "GET", "/v1/onboarding/templates") if t["is_default"]]
    assert len(defaults) == 1


async def test_the_case_completes_when_every_required_item_is_done_and_reopens(api):
    client, _ = api
    _, self_header, case = await _case(client)
    sign, badge = _item(case, "Sign offer"), _item(case, "Issue badge")

    # The new hire ticks their own item, but may not skip a required one or tick HR's.
    done = await ok(client, "PATCH", f"/v1/onboarding/items/{sign['id']}",
                    headers=self_header, json={"status": "COMPLETED", "notes": "Signed"})
    assert done["status"] == "COMPLETED" and done["completed_at"] and done["notes"] == "Signed"
    r = await client.patch(f"/v1/onboarding/items/{badge['id']}", headers=self_header,
                           json={"status": "COMPLETED"})
    assert r.status_code == 403

    # HR finishes the last required item: the optional one doesn't hold the case open.
    await ok(client, "PATCH", f"/v1/onboarding/items/{badge['id']}", json={"status": "COMPLETED"})
    finished = await ok(client, "GET", f"/v1/onboarding/cases/{case['id']}")
    assert finished["status"] == "COMPLETED" and finished["completed_at"]
    assert finished["completed_items"] == 2

    # Reopening a required item reopens the case, and clears its completion time.
    reopened = await ok(client, "PATCH", f"/v1/onboarding/items/{badge['id']}",
                        json={"status": "IN_PROGRESS"})
    assert reopened["completed_at"] is None
    again = await ok(client, "GET", f"/v1/onboarding/cases/{case['id']}")
    assert again["status"] == "IN_PROGRESS"


async def test_only_hr_may_skip_a_required_item(api):
    client, _ = api
    _, self_header, case = await _case(client)
    sign = _item(case, "Sign offer")
    r = await client.patch(f"/v1/onboarding/items/{sign['id']}", headers=self_header,
                           json={"status": "SKIPPED"})
    assert r.status_code == 403
    skipped = await ok(client, "PATCH", f"/v1/onboarding/items/{sign['id']}",
                       json={"status": "SKIPPED"})
    assert skipped["status"] == "SKIPPED"


async def test_cases_and_items_are_invisible_to_another_company(api):
    client, _ = api
    _, _, case = await _case(client)
    item = case["items"][0]
    await tenant(client)  # signs the client in as another company's SUPER_ADMIN
    assert (await client.get(f"/v1/onboarding/cases/{case['id']}")).status_code == 404
    r = await client.patch(f"/v1/onboarding/items/{item['id']}", json={"status": "COMPLETED"})
    assert r.status_code == 404
    assert case["id"] not in {c["id"] for c in await ok(client, "GET", "/v1/onboarding/cases")}


async def test_unknown_ids_are_404_not_500(api):
    client, _ = api
    await tenant(client)
    assert (await client.get("/v1/onboarding/cases/onboarding_case_00000000000000000000000000")
            ).status_code in (404, 422)

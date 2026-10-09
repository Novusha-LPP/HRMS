"""
HR maintains onboarding checklists from the UI: start from the standard one, edit it as a new
version without disturbing onboarding already under way, keep exactly one default, and retire
checklists that are no longer used.
"""

from datetime import date

import pytest

from tests.helpers import bearer, employee, ok, tenant

pytestmark = pytest.mark.database


def _checklist(name, *titles, default=False):
    return {
        "name": name,
        "is_default": default,
        "items": [
            {"title": t, "assignee_type": "HR", "due_days_from_hire": i, "sequence": i}
            for i, t in enumerate(titles)
        ],
    }


async def _defaults(client):
    return [t for t in await ok(client, "GET", "/v1/onboarding/templates") if t["is_default"]]


async def test_standard_checklist_is_a_starting_point_and_the_first_default(api):
    client, _ = api
    await tenant(client)
    standard = await ok(client, "POST", "/v1/onboarding/templates/standard")
    assert standard["is_default"] is True
    assert len(standard["items"]) == 10

    second = await ok(client, "POST", "/v1/onboarding/templates/standard")
    assert second["is_default"] is False  # one default only
    assert [t["id"] for t in await _defaults(client)] == [standard["id"]]


async def test_only_one_default(api):
    client, _ = api
    await tenant(client)
    first = await ok(client, "POST", "/v1/onboarding/templates", json=_checklist("Office", "A"))
    assert first["is_default"] is True  # first checklist is the default anyway
    plant = await ok(
        client, "POST", "/v1/onboarding/templates", json=_checklist("Plant", "B", default=True)
    )
    assert [t["id"] for t in await _defaults(client)] == [plant["id"]]


async def test_editing_saves_a_new_version_and_spares_started_onboarding(api):
    client, _ = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    v1 = await ok(client, "POST", "/v1/onboarding/templates", json=_checklist("Hire", "Old step"))
    first_hire, _ = await employee(client, company)
    started = await ok(
        client,
        "POST",
        "/v1/onboarding/cases",
        json={
            "employment_id": first_hire["id"],
            "template_id": v1["id"],
            "hire_date": str(date.today()),
        },
    )

    v2 = await ok(
        client,
        "PUT",
        f"/v1/onboarding/templates/{v1['id']}",
        json=_checklist("Hire", "New step", "Second new step"),
    )
    assert v2["id"] != v1["id"]
    assert v2["is_default"] is True  # the default stays the default
    listed = {t["id"] for t in await ok(client, "GET", "/v1/onboarding/templates")}
    assert v1["id"] not in listed and v2["id"] in listed

    # The case started on v1 keeps its own items.
    kept = await ok(client, "GET", f"/v1/onboarding/cases/{started['id']}")
    assert [i["title"] for i in kept["items"]] == ["Old step"]

    # A new case with no template uses the new default version.
    second_hire, _ = await employee(client, company)
    fresh = await ok(
        client,
        "POST",
        "/v1/onboarding/cases",
        json={"employment_id": second_hire["id"], "hire_date": str(date.today())},
    )
    assert [i["title"] for i in fresh["items"]] == ["New step", "Second new step"]

    # The retired version can't be edited again.
    stale = await client.put(f"/v1/onboarding/templates/{v1['id']}", json=_checklist("X", "Y"))
    assert stale.status_code == 404


async def test_deactivating(api):
    client, _ = api
    await tenant(client)
    default = await ok(client, "POST", "/v1/onboarding/templates", json=_checklist("Main", "A"))
    other = await ok(client, "POST", "/v1/onboarding/templates", json=_checklist("Other", "B"))

    blocked = await client.post(f"/v1/onboarding/templates/{default['id']}/deactivate")
    assert blocked.status_code == 409

    gone = await ok(client, "POST", f"/v1/onboarding/templates/{other['id']}/deactivate")
    assert gone["status"] == "INACTIVE"
    assert [t["id"] for t in await ok(client, "GET", "/v1/onboarding/templates")] == [default["id"]]


async def test_validation_and_access(api):
    client, _ = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    empty_title = await client.post(
        "/v1/onboarding/templates", json={"name": "X", "items": [{"title": ""}]}
    )
    assert empty_title.status_code == 422
    too_late = await client.post(
        "/v1/onboarding/templates",
        json={"name": "X", "items": [{"title": "Y", "due_days_from_hire": 1000}]},
    )
    assert too_late.status_code == 422

    _, login = await employee(client, company)
    staff = bearer(login["access_token"])
    denied = await client.post("/v1/onboarding/templates/standard", headers=staff)
    assert denied.status_code == 403

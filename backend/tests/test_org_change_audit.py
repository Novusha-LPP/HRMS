"""
Editing reference data (legal entities, org units, locations, jobs) now writes an
append-only change record — old value and new value, per field, per edit — instead
of just overwriting silently. Covers what the ERP-import work already established
for other tables (kyc_access_log, leave_balance_transactions): the record is
readable through the API, a no-op edit writes nothing, and only someone who could
edit the entity can see its history.
"""

import pytest

from tests.helpers import ok, org_basics, tenant

pytestmark = pytest.mark.database


async def _history(client, path):
    return await ok(client, "GET", path)


async def test_renaming_a_legal_entity_is_audited_with_old_and_new(api):
    client, _ = api
    await tenant(client)
    entities = await ok(client, "GET", "/v1/org/legal-entities")
    le = entities[0]

    history = await _history(client, f"/v1/org/legal-entities/{le['id']}/history")
    assert len(history) == 1
    assert history[0]["action"] == "CREATE"
    assert history[0]["changes"]["name"] == {"old": None, "new": le["name"]}
    assert history[0]["changed_by_name"]  # resolved to a real display name, not just an id

    updated = await ok(
        client, "PATCH", f"/v1/org/legal-entities/{le['id']}", json={"name": "Renamed Co"}
    )
    assert updated["name"] == "Renamed Co"

    history = await _history(client, f"/v1/org/legal-entities/{le['id']}/history")
    assert len(history) == 2
    latest = history[0]  # newest first
    assert latest["action"] == "UPDATE"
    assert latest["changes"] == {"name": {"old": le["name"], "new": "Renamed Co"}}
    # Untouched fields aren't recorded as if they'd changed.
    assert "short_name" not in latest["changes"]
    assert "country_code" not in latest["changes"]


async def test_a_no_op_edit_writes_nothing(api):
    client, _ = api
    await tenant(client)
    le = (await ok(client, "GET", "/v1/org/legal-entities"))[0]

    await ok(client, "PATCH", f"/v1/org/legal-entities/{le['id']}", json={"name": le["name"]})

    history = await _history(client, f"/v1/org/legal-entities/{le['id']}/history")
    assert len(history) == 1  # only the original CREATE — the no-op update added nothing
    assert history[0]["action"] == "CREATE"


async def test_financial_year_start_month_is_now_settable_and_audited(api):
    """The column existed but nothing could write it until this PATCH — regression guard."""
    client, _ = api
    await tenant(client)
    le = (await ok(client, "GET", "/v1/org/legal-entities"))[0]
    assert le["financial_year_start_month"] is None

    updated = await ok(
        client,
        "PATCH",
        f"/v1/org/legal-entities/{le['id']}",
        json={"financial_year_start_month": 4},
    )
    assert updated["financial_year_start_month"] == 4
    history = await _history(client, f"/v1/org/legal-entities/{le['id']}/history")
    assert history[0]["changes"]["financial_year_start_month"] == {"old": None, "new": 4}


async def test_org_unit_and_location_and_job_are_audited_too(api):
    client, _ = api
    await tenant(client)
    le = (await ok(client, "GET", "/v1/org/legal-entities"))[0]
    basics = await org_basics(client, le["id"])

    unit = await ok(
        client, "PATCH", f"/v1/org/org-units/{basics['org_unit_id']}", json={"name": "Ops Renamed"}
    )
    assert unit["name"] == "Ops Renamed"
    unit_history = await _history(client, f"/v1/org/org-units/{basics['org_unit_id']}/history")
    assert unit_history[0]["changes"]["name"]["new"] == "Ops Renamed"

    loc = await ok(
        client, "PATCH", f"/v1/org/locations/{basics['location_id']}", json={"city": "Mumbai"}
    )
    assert loc["city"] == "Mumbai"
    loc_history = await _history(client, f"/v1/org/locations/{basics['location_id']}/history")
    assert loc_history[0]["changes"]["city"] == {"old": None, "new": "Mumbai"}

    job = await ok(
        client, "PATCH", f"/v1/org/jobs/{basics['job_id']}", json={"title": "Senior Executive"}
    )
    assert job["title"] == "Senior Executive"
    job_history = await _history(client, f"/v1/org/jobs/{basics['job_id']}/history")
    assert job_history[0]["changes"]["title"]["new"] == "Senior Executive"


async def test_only_someone_who_could_edit_can_see_or_write_history(api):
    client, _ = api
    admin = await tenant(client)
    le = (await ok(client, "GET", "/v1/org/legal-entities"))[0]

    from httpx import ASGITransport, AsyncClient

    from hrms.main import app
    from tests.helpers import bearer, make_user, org_basics, person_and_employment

    basics = await org_basics(client, le["id"])
    emp = await person_and_employment(
        client, le["id"], legal_first_name="Regular", legal_last_name="Employee"
    )
    from tests.helpers import hire

    await hire(client, emp["id"], basics)
    email, password, _ = await make_user(client, emp["id"], role="EMPLOYEE", scope_type="SELF")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as plain:
        login = await ok(
            plain, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
        )
        headers = bearer(login["access_token"])

        r = await plain.get(f"/v1/org/legal-entities/{le['id']}/history", headers=headers)
        # A SELF-scoped EMPLOYEE has no legal_entity_ids in scope, so this 403s —
        # exactly like plain GET /v1/org/legal-entities already returns [] for them.
        assert r.status_code == 403

        r = await plain.patch(
            f"/v1/org/legal-entities/{le['id']}", json={"name": "Hijacked"}, headers=headers
        )
        assert r.status_code == 403  # org.write required, an EMPLOYEE role doesn't have it

    # The rejected attempt left no trace.
    history = await _history(client, f"/v1/org/legal-entities/{le['id']}/history")
    assert all(h["changes"].get("name", {}).get("new") != "Hijacked" for h in history)
    assert admin  # keeps the fixture referenced; avoids an unused-variable lint warning

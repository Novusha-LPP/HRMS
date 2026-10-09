"""
Sign-in slips: HR gives shop-floor staff (no email) temporary sign-in details in bulk. They sign
in with their employee number and must pick their own password first. Privileged logins, people
who have left, the caller's own login and other companies' staff are never touched.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.helpers import bearer, make_user, ok, person_and_employment, tenant

pytestmark = pytest.mark.database


async def _slips(client, ids, numeric=True, headers=None):
    return await ok(
        client,
        "POST",
        "/v1/users/sign-in-slips",
        json={"employment_ids": ids, "numeric": numeric},
        **({"headers": headers} if headers else {}),
    )


async def _entity(client):
    return (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"]


async def test_creates_logins_that_sign_in_with_the_employee_number(api):
    client, _ = api
    await tenant(client)
    le = await _entity(client)
    number = f"W-{uuid4().hex[:8]}"  # unique: login by number must not clash across tests
    worker = await person_and_employment(client, le, number=number)

    [slip] = await _slips(client, [worker["id"]])
    assert slip["outcome"] == "CREATED"
    assert slip["employee_number"] == number
    assert slip["temporary_password"].isdigit() and len(slip["temporary_password"]) == 8

    login = await client.post(
        "/v1/auth/login", json={"identifier": number, "password": slip["temporary_password"]}
    )
    assert login.status_code == 200, login.text
    assert login.json()["user"]["must_change_password"] is True


async def test_reissuing_replaces_the_password(api):
    client, _ = api
    await tenant(client)
    number = f"W-{uuid4().hex[:8]}"
    worker = await person_and_employment(client, await _entity(client), number=number)
    [first] = await _slips(client, [worker["id"]], numeric=False)
    assert len(first["temporary_password"]) == 10 and not first["temporary_password"].isdigit()

    [second] = await _slips(client, [worker["id"]])
    assert second["outcome"] == "RESET"
    old = await client.post(
        "/v1/auth/login", json={"identifier": number, "password": first["temporary_password"]}
    )
    assert old.status_code == 401
    new = await client.post(
        "/v1/auth/login", json={"identifier": number, "password": second["temporary_password"]}
    )
    assert new.status_code == 200


async def test_skips_what_must_not_be_reset(api):
    client, db = api
    await tenant(client)
    le = await _entity(client)
    other = await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Other Co"})

    hr_person = await person_and_employment(client, le)
    await make_user(
        client, hr_person["id"], role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    leaver = await person_and_employment(client, le)
    await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json={"employment_id": leaver["id"], "type": "SEPARATION", "effective_date": "2021-01-01"},
    )
    elsewhere = await person_and_employment(client, other["id"])
    fine = await person_and_employment(client, le)

    results = await _slips(client, [hr_person["id"], leaver["id"], elsewhere["id"], fine["id"]])
    outcome = {r["employment_id"]: (r["outcome"], r["reason"]) for r in results}
    assert outcome[hr_person["id"]][0] == "SKIPPED" and "HR" in outcome[hr_person["id"]][1]
    assert outcome[leaver["id"]] == ("SKIPPED", "Has left")
    assert outcome[fine["id"]][0] == "CREATED"
    # The tenant admin covers every company, so this one is created too...
    assert outcome[elsewhere["id"]][0] == "CREATED"
    assert all(r["temporary_password"] is None for r in results if r["outcome"] == "SKIPPED")

    # ...but an HR manager scoped to the first company can't touch the other company's staff.
    email, password, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    hr_login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    scoped = await _slips(client, [elsewhere["id"]], headers=bearer(hr_login["access_token"]))
    assert scoped[0]["outcome"] == "SKIPPED"
    assert scoped[0]["reason"] == "Outside the companies you manage"

    # The change history records the issue, never the password.
    async with db.connect() as conn:
        logged = (
            await conn.execute(
                text(
                    "SELECT entity_id, changes::text FROM entity_change_log "
                    "WHERE entity_type = 'user_account'"
                )
            )
        ).all()
    issued = [r for r in results if r["temporary_password"]]
    assert sum("issued on a sign-in slip" in changes for _, changes in logged) >= len(issued)
    for _, changes in logged:
        assert all(r["temporary_password"] not in changes for r in issued)


async def test_employees_cannot_issue_slips(api):
    client, _ = api
    await tenant(client)
    le = await _entity(client)
    me = await person_and_employment(client, le)
    email, password, _ = await make_user(client, me["id"])
    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    denied = await client.post(
        "/v1/users/sign-in-slips",
        json={"employment_ids": [me["id"]]},
        headers=bearer(login["access_token"]),
    )
    assert denied.status_code == 403

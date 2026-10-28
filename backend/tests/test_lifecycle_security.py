"""
Tenant and company isolation for everything the leavers / rejoining work adds: row-level security
on every new table, another tenant's administrator reaching nothing, and an administrator for one
company reaching nothing of another company's people.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hrms.core.ids import to_uuid
from tests.helpers import (
    client_from,
    hire,
    make_user,
    ok,
    org_basics,
    person_and_employment,
    tenant,
)

pytestmark = pytest.mark.database

TODAY = date.today()
NEW_TABLES = (
    "employment_spells",
    "rejoin_records",
    "leave_separation_rules",
    "leave_separation_settlements",
    "rejoin_policies",
    "prior_service",
    "company_transfers",
)


async def _populated_tenant(client):
    """A tenant with a row in every new table."""
    admin = await tenant(client)
    first = admin["user"]["legal_entities"][0]["id"]
    second = (
        await ok(client, "POST", "/v1/org/legal-entities", json={"name": "Sister", "country": "IN"})
    )["id"]
    placement_a = await org_basics(client, first)
    placement_b = await org_basics(client, second)
    emp = await person_and_employment(client, first)
    await hire(client, emp["id"], placement_a)
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
    await ok(
        client,
        "POST",
        "/v1/leave/separation-rules",
        json={"on_separation": "HOLD", "hold_days": 30, "effective_from": "2020-01-01"},
    )
    await ok(
        client,
        "POST",
        "/v1/people/rejoin-policies",
        json={"default_mode": "CONTINUE", "effective_from": "2020-01-01"},
    )
    await ok(
        client,
        "POST",
        f"/v1/persons/{emp['person_id']}/prior-service",
        json={
            "employer_name": "Earlier Co",
            "from_date": "2015-01-01",
            "to_date": "2016-01-01",
        },
    )
    await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "SEPARATION",
            "effective_date": (TODAY - timedelta(days=5)).isoformat(),
            "reason_code": "RESIGNATION",
        },
    )
    back = await client.post(
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "REHIRE",
            "effective_date": TODAY.isoformat(),
            "changes": placement_a,
        },
    )
    assert back.status_code == 201, back.text
    moved = await client.post(
        "/v1/people/transfers",
        json={
            "employment_id": emp["id"],
            "legal_entity_id": second,
            "effective_date": TODAY.isoformat(),
            "placement": placement_b,
            "employee_number": f"SEC-{uuid4().hex[:5]}",
        },
    )
    assert moved.status_code == 201, moved.text
    return admin, first, second, emp, lt, moved.json()


async def test_row_level_security_isolates_every_new_table(api):
    client, admin_engine = api
    admin, _, _, emp, _, _ = await _populated_tenant(client)
    mine = await _tenant_id(admin_engine, emp)
    url = admin_engine.url.set(username="hrms_app", password="hrms_app_dev_password")
    app = create_async_engine(url, poolclass=NullPool)
    try:
        for table in NEW_TABLES:
            async with app.begin() as conn:
                none = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
                assert none == 0, f"{table} readable without a tenant"
            async with app.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(mine)}
                )
                own = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
                assert own > 0, f"{table} has no row for its own tenant"
            async with app.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(uuid4())}
                )
                other = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
                assert other == 0, f"{table} leaks across tenants"
                # Rows of another tenant cannot even be updated or deleted from here.
                touched = await conn.execute(text(f"UPDATE {table} SET tenant_id = tenant_id"))
                assert touched.rowcount == 0, f"{table} can be updated across tenants"
                removed = await conn.execute(text(f"DELETE FROM {table}"))
                assert removed.rowcount == 0, f"{table} can be deleted across tenants"
    finally:
        await app.dispose()


async def _tenant_id(engine, emp):
    async with engine.connect() as conn:
        return await conn.scalar(
            text("SELECT tenant_id FROM employments WHERE id = :e"), {"e": to_uuid(emp["id"])}
        )


async def test_another_tenants_administrator_reaches_nothing(api):
    client, _ = api
    _, first, second, emp, _, moved = await _populated_tenant(client)
    person, employment = emp["person_id"], emp["id"]
    new_employment = moved["to_employment_id"]
    async with client_from("203.0.113.77") as other:
        await tenant(other)
        gone = {403, 404}
        for path in (
            f"/v1/employees/{employment}/employment-history",
            f"/v1/employees/{employment}/rejoin-preview",
            f"/v1/leave/separation-preview?employment_id={employment}",
            f"/v1/people/transfer-preview?employment_id={new_employment}&legal_entity_id={first}",
            f"/v1/persons/{person}/prior-service",
        ):
            assert (await other.get(path)).status_code in gone, path
        # Lists that cannot name a row simply come back empty.
        assert (await ok(other, "GET", f"/v1/persons/{person}/employments")) == []
        assert (await ok(other, "GET", "/v1/leave/separation-rules")) == []
        assert (await ok(other, "GET", "/v1/people/rejoin-policies")) == []
        for kind in (
            "people/reports/rejoins",
            "people/reports/company-transfers",
            "leave/reports/separation-settlements",
        ):
            assert (await ok(other, "GET", f"/v1/{kind}"))["rows"] == [], kind
        settlements = await other.get(
            f"/v1/leave/separation-settlements?employment_id={employment}"
        )
        assert settlements.status_code in gone or settlements.json() == []
        # Writes aimed at this tenant's rows are refused.
        write = await other.post(
            "/v1/people/transfers",
            json={
                "employment_id": new_employment,
                "legal_entity_id": first,
                "effective_date": TODAY.isoformat(),
                "placement": {"org_unit_id": "ou_x", "location_id": "loc_x", "job_id": "job_x"},
            },
        )
        assert write.status_code in gone | {422}
        prior = await other.post(
            f"/v1/persons/{person}/prior-service",
            json={"employer_name": "X", "from_date": "2010-01-01", "to_date": "2011-01-01"},
        )
        assert prior.status_code in gone


async def test_an_administrator_for_one_company_reaches_nothing_of_another(api):
    client, _ = api
    admin, first, second, emp, _, moved = await _populated_tenant(client)
    # The person now works for the second company; an administrator for the first only
    # still manages the old, separated employment but not the new one.
    email, password, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[first]
    )
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    new_employment = moved["to_employment_id"]
    for path in (
        f"/v1/employees/{new_employment}/employment-history",
        f"/v1/employees/{new_employment}/rejoin-preview",
        f"/v1/leave/separation-preview?employment_id={new_employment}",
        f"/v1/people/transfer-preview?employment_id={new_employment}&legal_entity_id={first}",
    ):
        assert (await client.get(path, headers=headers)).status_code in {403, 404}, path
    visible = await ok(
        client, "GET", f"/v1/persons/{emp['person_id']}/employments", headers=headers
    )
    assert {e["employment_id"] for e in visible} == {emp["id"]}  # only their own company's
    report = await ok(client, "GET", "/v1/people/reports/company-transfers", headers=headers)
    assert len(report["rows"]) == 1  # the move out of their company is theirs to see
    to_second = await ok(client, "GET", "/v1/people/reports/rejoins", headers=headers)
    assert all(row[2] != "Sister" for row in to_second["rows"])


async def test_system_keys_cannot_be_smuggled_in_through_changes(api):
    client, _ = api
    admin, first, _, emp, _, _ = await _populated_tenant(client)
    # Someone currently employed (the moved person's new employment) in the second company.
    other = await person_and_employment(client, first)
    placement = await org_basics(client, first)
    await hire(client, other["id"], placement)
    for key in ("skip_leave_settlement", "rejoin"):
        refused = await client.post(
            "/v1/personnel-actions",
            json={
                "employment_id": other["id"],
                "type": "SEPARATION",
                "effective_date": TODAY.isoformat(),
                "reason_code": "RESIGNATION",
                "changes": {key: True},
            },
        )
        assert refused.status_code == 422, (key, refused.text)
    assert (await ok(client, "GET", f"/v1/employees/{other['id']}"))[
        "employment_state"
    ] != "SEPARATED"


async def test_settings_changes_are_recorded_with_who_made_them(api):
    client, admin_engine = api
    _, _, _, emp, _, _ = await _populated_tenant(client)
    mine = await _tenant_id(admin_engine, emp)
    rule = await ok(
        client,
        "POST",
        "/v1/leave/separation-rules",
        json={"on_separation": "LAPSE", "effective_from": "2021-01-01"},
    )
    assert (await client.delete(f"/v1/leave/separation-rules/{rule['id']}")).status_code == 204
    async with admin_engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT action FROM entity_change_log WHERE tenant_id = :t "
                        "AND entity_type = 'leave_separation_rule' ORDER BY changed_at"
                    ),
                    {"t": mine},
                )
            )
            .scalars()
            .all()
        )
        kinds = (
            (
                await conn.execute(
                    text("SELECT DISTINCT entity_type FROM entity_change_log WHERE tenant_id = :t"),
                    {"t": mine},
                )
            )
            .scalars()
            .all()
        )
    assert "CREATE" in rows and ("ARCHIVE" in rows or "UPDATE" in rows)
    for entity in ("rejoin_policy", "prior_service", "company_transfer"):
        assert entity in kinds, entity

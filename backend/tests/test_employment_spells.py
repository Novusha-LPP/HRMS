"""
Each stint of an employment is recorded, and a rejoin leaves a decision record.

Hire opens stint 1, separation closes it, a rejoin opens the next and records that earlier
service continued. Today's rejoin behaviour (same employment, balances kept) is unchanged.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hrms.core.ids import to_uuid
from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

TODAY = date.today()


async def _setup(client):
    await tenant(client)
    le = (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"]
    placement = await org_basics(client, le)
    emp = await person_and_employment(client, le)
    await hire(client, emp["id"], placement)
    return placement, emp


async def _act(client, emp_id, kind, changes=None, when=TODAY, reason=None):
    body = {"employment_id": emp_id, "type": kind, "effective_date": when.isoformat()}
    if changes:
        body["changes"] = changes
    if reason:
        body["reason_code"] = reason
    return await client.post("/v1/personnel-actions", json=body)


async def _spells(engine, emp_id):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT spell_no, joined_on, left_on, exit_reason FROM employment_spells "
                "WHERE employment_id = :e ORDER BY spell_no"
            ),
            {"e": to_uuid(emp_id)},
        )
        return [tuple(r) for r in rows]


async def _employment(engine, emp_id):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT hire_date, continuity_start_date, current_spell_no "
                "FROM employments WHERE id = :e"
            ),
            {"e": to_uuid(emp_id)},
        )
        return row.one()


async def _records(engine, emp_id):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT mode, break_start, break_end, break_condoned, previous_spell_id, "
                "new_spell_id, personnel_action_id FROM rejoin_records "
                "WHERE employment_id = :e ORDER BY created_at"
            ),
            {"e": to_uuid(emp_id)},
        )
        return list(rows)


async def test_a_new_employment_starts_with_its_first_stint(api):
    client, engine = api
    _, emp = await _setup(client)
    assert await _spells(engine, emp["id"]) == [(1, date(2020, 1, 1), None, None)]
    hire_date, continuity, current = await _employment(engine, emp["id"])
    assert (continuity, current) == (hire_date, 1)


async def test_separation_closes_the_stint_with_its_reason(api):
    client, engine = api
    _, emp = await _setup(client)
    assert (await _act(client, emp["id"], "SEPARATION", reason="RESIGNATION")).status_code == 201
    assert await _spells(engine, emp["id"]) == [(1, date(2020, 1, 1), TODAY, "RESIGNATION")]


async def test_rejoining_opens_the_next_stint_and_records_that_service_continued(api):
    client, engine = api
    placement, emp = await _setup(client)
    await _act(client, emp["id"], "SEPARATION", reason="RESIGNATION", when=TODAY - timedelta(10))
    rejoined = await _act(client, emp["id"], "REHIRE", changes=placement)
    assert rejoined.status_code == 201, rejoined.text

    assert await _spells(engine, emp["id"]) == [
        (1, date(2020, 1, 1), TODAY - timedelta(10), "RESIGNATION"),
        (2, TODAY, None, None),
    ]
    hire_date, continuity, current = await _employment(engine, emp["id"])
    assert (continuity, current) == (hire_date, 2)  # earlier service still counts
    (record,) = await _records(engine, emp["id"])
    assert record.mode == "CONTINUE" and record.break_condoned is True
    assert (record.break_start, record.break_end) == (TODAY - timedelta(10), TODAY)
    assert record.previous_spell_id != record.new_spell_id
    assert record.personnel_action_id is not None


async def test_a_refused_rejoin_leaves_no_trace(api):
    client, engine = api
    placement, emp = await _setup(client)
    refused = await _act(client, emp["id"], "REHIRE", changes=placement)  # still employed
    assert refused.status_code == 409
    assert len(await _spells(engine, emp["id"])) == 1
    assert await _records(engine, emp["id"]) == []


async def test_several_rejoins_keep_every_stint_in_order(api):
    client, engine = api
    placement, emp = await _setup(client)
    for gap in (30, 20):
        await _act(
            client, emp["id"], "SEPARATION", reason="RESIGNATION", when=TODAY - timedelta(gap)
        )
        assert (
            await _act(
                client, emp["id"], "REHIRE", changes=placement, when=TODAY - timedelta(gap - 5)
            )
        ).status_code == 201
    spells = await _spells(engine, emp["id"])
    assert [s[0] for s in spells] == [1, 2, 3]
    assert spells[0][2] is not None and spells[1][2] is not None and spells[2][2] is None
    assert (await _employment(engine, emp["id"])).current_spell_no == 3
    assert len(await _records(engine, emp["id"])) == 2


async def test_the_app_role_sees_no_stints_without_a_tenant(api):
    client, admin = api
    _, emp = await _setup(client)
    url = admin.url.set(username="hrms_app", password="hrms_app_dev_password")
    app_engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with app_engine.connect() as conn:
            for table in ("employment_spells", "rejoin_records"):
                count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
                assert count == 0, table
    finally:
        await app_engine.dispose()

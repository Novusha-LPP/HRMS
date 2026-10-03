"""PolicyResolver must return exactly what resolve_policy does — only with far fewer queries."""

from datetime import date, time

import pytest
from sqlalchemy import event, text

from hrms.core import database
from hrms.core.ids import to_uuid
from hrms.modules.policy.engine import PolicyResolver, default_policy, resolve_policy
from tests.helpers import hire, ok, org_basics, person_and_employment, tenant

pytestmark = pytest.mark.database

WORK_DAY = date(2026, 9, 28)


async def _template(client, name, start, **extra):
    return await ok(
        client,
        "POST",
        "/v1/policies/templates",
        json={"name": name, "expected_start_time": start, "expected_end_time": "19:00", **extra},
    )


async def _assign(client, template, **target):
    return await ok(
        client,
        "POST",
        "/v1/policies/assignments",
        json={"policy_template_id": template["id"], "effective_from": "2020-01-01", **target},
    )


async def test_resolver_matches_resolve_policy_on_every_tier(api):
    client, _ = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company = admin["user"]["legal_entities"][0]["id"]
    other_company = (
        await ok(
            client, "POST", "/v1/org/legal-entities", json={"name": "Other", "country_code": "IN"}
        )
    )["id"]
    base = await org_basics(client, company)
    other_base = await org_basics(client, other_company)

    head = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Head",
            "type": "DEPARTMENT",
            "legal_entity_id": company,
            "effective_from": "2020-01-01",
        },
    )
    child = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Child",
            "type": "DEPARTMENT",
            "legal_entity_id": company,
            "parent_id": head["id"],
            "effective_from": "2020-01-01",
        },
    )

    await _template(client, "Tenant default", "08:00", is_default=True)
    company_wide = await _template(client, "Company", "09:00")
    department = await _template(client, "Department", "10:00", grace_late_minutes=5)
    personal = await _template(client, "Personal", "11:00")
    await _assign(client, company_wide, legal_entity_id=company)
    await _assign(client, department, org_unit_id=head["id"])  # inherited by Child

    async def person(number, entity, placement, unit=None):
        emp = await person_and_employment(client, entity, number)
        await hire(client, emp["id"], {**placement, **({"org_unit_id": unit} if unit else {})})
        return emp

    in_child = await person("C1", company, base, child["id"])  # dept tier (via ancestor)
    in_head = await person("H1", company, base, head["id"])  # dept tier (direct)
    in_plain = await person("P1", company, base)  # company-wide tier
    personal_emp = await person("X1", company, base, child["id"])  # personal beats everything
    await _assign(client, personal, employment_id=personal_emp["id"], grace_late_minutes_override=0)
    elsewhere = await person("E1", other_company, other_base)  # falls to the tenant default

    people = {"C1": in_child, "H1": in_head, "P1": in_plain, "X1": personal_emp, "E1": elsewhere}
    expected_start = {
        "C1": time(10, 0),
        "H1": time(10, 0),
        "P1": time(9, 0),
        "X1": time(11, 0),
        "E1": time(8, 0),
    }

    async with database.AsyncSessionLocal() as session:
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        rows = (
            (
                await session.execute(
                    text("""
            SELECT e.id, e.employee_number, e.legal_entity_id, a.org_unit_id
            FROM employments e LEFT JOIN assignments a
              ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
             AND a.effective_from <= :d AND (a.effective_to IS NULL OR a.effective_to > :d)
            WHERE e.tenant_id = :t"""),
                    {"d": WORK_DAY, "t": tid},
                )
            )
            .mappings()
            .all()
        )
        assert {r["employee_number"] for r in rows} == set(people)

        resolver = PolicyResolver(session, tid, WORK_DAY)
        for r in rows:
            direct = await resolve_policy(r["id"], WORK_DAY, session, tid)
            batched = await resolver.resolve(
                r["id"], org_unit_id=r["org_unit_id"], legal_entity_id=r["legal_entity_id"]
            )
            assert batched == direct, r["employee_number"]
            assert direct.expected_start_time == expected_start[r["employee_number"]]
        assert (
            await resolve_policy(to_uuid(in_child["id"]), WORK_DAY, session, tid)
        ).grace_late_minutes == 5
        assert (
            await resolve_policy(to_uuid(personal_emp["id"]), WORK_DAY, session, tid)
        ).grace_late_minutes == 0


async def test_resolver_uses_a_handful_of_queries_not_eight_per_employee(api):
    client, _ = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company = admin["user"]["legal_entities"][0]["id"]
    base = await org_basics(client, company)
    await _assign(client, await _template(client, "Company", "09:00"), legal_entity_id=company)
    people = []
    for i in range(12):
        emp = await person_and_employment(client, company, f"N{i}")
        await hire(client, emp["id"], base)
        people.append(emp)

    async with database.AsyncSessionLocal() as session:
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        rows = (
            (
                await session.execute(
                    text("""
            SELECT e.id, e.legal_entity_id, a.org_unit_id FROM employments e
            LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
            WHERE e.tenant_id = :t"""),
                    {"t": tid},
                )
            )
            .mappings()
            .all()
        )
        counted = []
        sync_engine = (
            session.get_bind().sync_engine if hasattr(session.get_bind(), "sync_engine") else None
        )
        target = sync_engine or session.get_bind()
        event.listen(target, "before_cursor_execute", lambda *a, **k: counted.append(1))
        resolver = PolicyResolver(session, tid, WORK_DAY)
        for r in rows:
            await resolver.resolve(
                r["id"], org_unit_id=r["org_unit_id"], legal_entity_id=r["legal_entity_id"]
            )
        batched_queries = len(counted)
        counted.clear()
        for r in rows:
            await resolve_policy(r["id"], WORK_DAY, session, tid)
        per_employee_queries = len(counted)
    assert len(rows) == 12
    assert batched_queries <= 6, batched_queries  # personal-set + one shared resolution
    assert per_employee_queries >= 12 * 4, per_employee_queries  # what it used to cost


async def test_without_any_template_the_deployment_fallback_applies(api):
    client, _ = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company = admin["user"]["legal_entities"][0]["id"]
    emp = await person_and_employment(client, company)
    async with database.AsyncSessionLocal() as session:
        await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
        policy = await resolve_policy(to_uuid(emp["id"]), WORK_DAY, session, tid)
    assert policy == default_policy()


async def test_resolver_query_count_is_constant_across_many_departments(api):
    from uuid import uuid4

    from sqlalchemy import event, text

    client, _ = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company = admin["user"]["legal_entities"][0]["id"]
    units = []
    for index in range(20):
        unit = await ok(
            client,
            "POST",
            "/v1/org/org-units",
            json={
                "name": f"Budget department {index}",
                "type": "DEPARTMENT",
                "legal_entity_id": company,
                "effective_from": "2020-01-01",
            },
        )
        units.append(to_uuid(unit["id"]))
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)}
        )
        counted = []

        def observe(*args, **kwargs):
            counted.append(1)

        target = session.get_bind()
        event.listen(target, "before_cursor_execute", observe)
        try:
            resolver = PolicyResolver(session, tid, WORK_DAY)
            for unit in units:
                await resolver.resolve(uuid4(), org_unit_id=unit, legal_entity_id=to_uuid(company))
            assert len(counted) == 3
        finally:
            event.remove(target, "before_cursor_execute", observe)

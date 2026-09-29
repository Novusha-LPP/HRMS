"""
No GET endpoint may answer 5xx for any kind of caller.

The HR dashboard once worked for the group administrator and returned a 500 for
every company-scoped HR manager — a bug no test could see, because nothing called
the endpoint as anyone but an admin. This calls every GET route as three very
different callers, against a tenant with realistic data in it, and fails on any
server error (4xx — forbidden, not found, missing parameter — is fine).
"""

import re
from datetime import date
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from hrms.core.ids import to_typed_id, to_uuid
from hrms.main import app
from tests.helpers import (
    bearer,
    hire,
    make_user,
    ok,
    org_basics,
    person_and_employment,
    tenant,
)

pytestmark = pytest.mark.database

SKIPPED_PREFIXES = ("/docs", "/redoc", "/openapi", "/health", "/v1/platform")


def _get_routes():
    for path, item in app.openapi()["paths"].items():
        if "get" in item and not path.startswith(SKIPPED_PREFIXES):
            yield path


ROUTES = sorted(_get_routes())


def _fill(path: str, known: dict[str, str]) -> str:
    """Fill path parameters with real ids where known, else a well-formed unknown one."""

    def repl(match):
        name = match.group(1)
        return known.get(name) or to_typed_id("resource", uuid4())

    return re.sub(r"\{(\w+)\}", repl, path)


async def test_no_get_endpoint_returns_a_server_error_for_any_caller(api):
    client, engine = api
    admin = await tenant(client)
    tid = to_uuid(admin["user"]["tenant_id"])
    company = admin["user"]["legal_entities"][0]["id"]
    other = (
        await ok(
            client, "POST", "/v1/org/legal-entities", json={"name": "Other", "country_code": "IN"}
        )
    )["id"]
    placement = await org_basics(client, company)
    staff = []
    for i in range(3):
        emp = await person_and_employment(
            client, company, f"S{i}", date_of_birth="1991-04-05", gender="F"
        )
        await hire(client, emp["id"], placement)
        staff.append(emp)
    stranger = await person_and_employment(client, other, "O0")
    await hire(client, stranger["id"], await org_basics(client, other))

    hr = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company]
    )
    mgr = await make_user(client, staff[0]["id"], role="MANAGER", scope_type="DIRECT_REPORTS")
    own = await make_user(client, staff[1]["id"])

    # Give the list/detail endpoints something to chew on.
    await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={"name": "Casual", "code": "CL", "days_per_year": 12},
    )
    await ok(client, "POST", "/v1/policies/templates", json={"name": "Std", "is_default": True})
    await ok(client, "GET", "/v1/reports")  # seeds the default report definitions
    for emp in staff:
        await ok(
            client,
            "POST",
            "/v1/time/punches",
            headers=bearer(
                (
                    await ok(
                        client,
                        "POST",
                        "/v1/auth/login",
                        json={"identifier": own[0], "password": own[1]},
                    )
                )["access_token"]
            ),
            json={"punch_type": "IN"},
        ) if emp is staff[1] else None
    async with engine.begin() as conn:
        await conn.execute(
            text("""INSERT INTO employee_kyc_records (tenant_id, id, employment_id, status)
                                   VALUES (:t, :i, :e, 'SUBMITTED')"""),
            {"t": tid, "i": uuid4(), "e": to_uuid(staff[2]["id"])},
        )

    callers = {"group admin": dict(client.headers)}
    for label, (email, pw, _) in (
        ("company HR manager", hr),
        ("manager", mgr),
        ("plain employee", own),
    ):
        token = (
            await ok(client, "POST", "/v1/auth/login", json={"identifier": email, "password": pw})
        )["access_token"]
        callers[label] = bearer(token)

    known = {
        "employment_id": staff[1]["id"],
        "manager_employment_id": staff[0]["id"],
        "person_id": staff[1]["person_id"],
    }
    failures = []
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as raw:
        for label, headers in callers.items():
            for route in ROUTES:
                url = _fill(route, known)
                if "{" in route and "employment_id" in route:
                    url = url  # path already filled
                params = {"employment_id": staff[1]["id"], "work_date": str(date.today())}
                response = await raw.get(url, headers=headers, params=params)
                if response.status_code >= 500:
                    failures.append(
                        f"{label}: GET {route} -> {response.status_code} {response.text[:160]}"
                    )
    assert not failures, "\n".join(failures)
    assert len(ROUTES) >= 40  # guard against the route discovery silently returning nothing


async def test_concurrent_first_report_listing_seeds_the_defaults_only_once(api):
    import asyncio

    client, _ = api
    await tenant(client)
    first = await asyncio.gather(*[client.get("/v1/reports") for _ in range(5)])
    assert all(r.status_code == 200 for r in first)
    names = [r["name"] for r in (await ok(client, "GET", "/v1/reports")) if r["is_system"]]
    assert names and len(names) == len(set(names)), names

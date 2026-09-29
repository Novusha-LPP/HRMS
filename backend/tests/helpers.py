"""Shared building blocks for the HTTP-level tests (fake data only)."""

from datetime import date
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from hrms.main import app

PASSWORD = "Test-password-123"


async def ok(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    assert response.is_success, (method, path, response.status_code, response.text)
    return response.json() if response.status_code != 204 else None


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def client_from(ip: str) -> AsyncClient:
    """A client whose requests appear to come from `ip` (throttle counters are per IP)."""
    return AsyncClient(transport=ASGITransport(app=app, client=(ip, 4321)), base_url="http://test")


async def tenant(client):
    """Register a fresh company and sign the client in as its SUPER_ADMIN."""
    result = await ok(
        client,
        "POST",
        "/v1/auth/register-company",
        json={
            "company_name": "Regression " + uuid4().hex[:8],
            "admin_email": uuid4().hex + "@example.com",
            "admin_password": PASSWORD,
        },
    )
    client.headers["Authorization"] = "Bearer " + result["access_token"]
    return result


async def org_basics(client, legal_entity, headers=None):
    """A location, a department and a job title — what a HIRE needs to place someone."""
    kw = {"headers": headers} if headers else {}
    loc = await ok(
        client,
        "POST",
        "/v1/org/locations",
        json={"name": "HQ", "type": "OFFICE", "legal_entity_id": legal_entity},
        **kw,
    )
    unit = await ok(
        client,
        "POST",
        "/v1/org/org-units",
        json={
            "name": "Ops",
            "type": "DEPARTMENT",
            "legal_entity_id": legal_entity,
            "effective_from": "2020-01-01",
        },
        **kw,
    )
    job = await ok(client, "POST", "/v1/org/jobs", json={"title": "Executive"}, **kw)
    return {"location_id": loc["id"], "org_unit_id": unit["id"], "job_id": job["id"]}


async def person_and_employment(client, legal_entity, number=None, headers=None, **person):
    kw = {"headers": headers} if headers else {}
    p = await ok(
        client,
        "POST",
        "/v1/persons",
        json={"legal_first_name": "Test", "legal_last_name": uuid4().hex[:6], **person},
        **kw,
    )
    return await ok(
        client,
        "POST",
        "/v1/employees",
        json={
            "person_id": p["id"],
            "legal_entity_id": legal_entity,
            "employee_number": number or uuid4().hex[:8],
            "hire_date": "2020-01-01",
        },
        **kw,
    )


async def hire(client, employment_id, placement, when=None, headers=None):
    kw = {"headers": headers} if headers else {}
    return await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json={
            "employment_id": employment_id,
            "type": "HIRE",
            "effective_date": str(when or date(2020, 1, 1)),
            "changes": placement,
        },
        **kw,
    )


async def make_user(
    client,
    employment_id=None,
    role="EMPLOYEE",
    scope_type="SELF",
    legal_entity_ids=None,
    must_change_password=False,
    headers=None,
    password=PASSWORD,
):
    """Create a login through the API; returns (email, password, response json)."""
    email = uuid4().hex + "@example.com"
    body = {
        "email": email,
        "password": password,
        "role": role,
        "scope_type": scope_type,
        "must_change_password": must_change_password,
    }
    if employment_id:
        body["employment_id"] = employment_id
    if legal_entity_ids:
        body["legal_entity_ids"] = legal_entity_ids
    kw = {"headers": headers} if headers else {}
    created = await ok(client, "POST", "/v1/users", json=body, **kw)
    return email, password, created


async def sign_in(client, identifier, password=PASSWORD):
    """POST /v1/auth/login without asserting the outcome."""
    return await client.post(
        "/v1/auth/login", json={"identifier": identifier, "password": password}
    )


async def employee(client, legal_entity, number=None):
    """A person + employment + EMPLOYEE/SELF login; returns (employment, login json)."""
    emp = await person_and_employment(client, legal_entity, number)
    email, password, _ = await make_user(client, emp["id"])
    login = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": password})
    return emp, login

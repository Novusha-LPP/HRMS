"""Shared set-up for the integration (connected apps) tests: fake data only."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from tests.helpers import ok, org_basics, tenant

ALL_SCOPES = [
    "employees.sync",
    "employees.read",
    "passwords.sync",
    "sessions.issue",
    "org.read",
    "events.read",
    "attendance.read",
    "leave.read",
]


class World:
    """A company, its org structure, and a connected two-way app with a key."""

    def __init__(self, client, admin_headers, legal_entity, placement, names, app, key):
        self.client = client
        self.admin = admin_headers
        self.legal_entity = legal_entity
        self.placement = placement
        self.names = names
        self.app = app
        self.key = key

    @property
    def erp(self) -> dict[str, str]:
        return {"X-API-Key": self.key}

    async def put(self, external_id: str, expect: int | None = None, **body):
        response = await self.client.put(
            f"/v1/integrations/employees/{external_id}", json=body, headers=self.erp
        )
        if expect is not None:
            assert response.status_code == expect, response.text
        return response

    def new_hire(self, **extra):
        base = {
            "first_name": "Asha",
            "last_name": "K" + uuid4().hex[:5],
            "company": self.names["company"],
            "department": self.names["department"],
            "location": self.names["location"],
            "designation": self.names["designation"],
            "hire_date": str(date.today() - timedelta(days=30)),
            "employee_code": "E" + uuid4().hex[:7].upper(),
        }
        base.update(extra)
        return base

    async def publish(self, settings: dict, legal_entity_id: str | None = None, when=None):
        draft = await ok(
            self.client,
            "POST",
            f"/v1/admin/integrations/apps/{self.app['id']}/profiles",
            json={"legal_entity_id": legal_entity_id, "settings": settings}
            if legal_entity_id
            else {"settings": settings},
            headers=self.admin,
        )
        return await ok(
            self.client,
            "POST",
            f"/v1/admin/integrations/profiles/{draft['id']}/publish",
            json={"effective_from": str(when or date.today())},
            headers=self.admin,
        )

    async def current_settings(self) -> dict:
        return (
            await ok(
                self.client,
                "GET",
                f"/v1/admin/integrations/apps/{self.app['id']}/settings",
                headers=self.admin,
            )
        )["settings"]


async def make_app(client, admin, code="ERP", kind="TWO_WAY", scopes=None, **key_options):
    app = await ok(
        client,
        "POST",
        "/v1/admin/integrations/apps",
        json={"code": code, "name": f"{code} system", "kind": kind},
        headers=admin,
    )
    key = await ok(
        client,
        "POST",
        f"/v1/admin/integrations/apps/{app['id']}/keys",
        json={"name": "server", "scopes": scopes or ALL_SCOPES, **key_options},
        headers=admin,
    )
    return app, key


async def world(client) -> World:
    registered = await tenant(client)
    admin = {"Authorization": client.headers["Authorization"]}
    legal_entity = registered["user"]["legal_entities"][0]["id"]
    company = registered["user"]["legal_entities"][0]["name"]
    placement = await org_basics(client, legal_entity)
    app, key = await make_app(client, admin)
    names = {"company": company, "department": "Ops", "location": "HQ", "designation": "Executive"}
    return World(client, admin, legal_entity, placement, names, app, key["key"])

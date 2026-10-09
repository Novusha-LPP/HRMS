"""GET/PATCH /v1/me/preferences — each person's own theme and dashboard choice."""

import pytest

from tests.helpers import employee, make_user, ok, tenant

pytestmark = pytest.mark.database

PASSWORD = "Test-password-123"


@pytest.mark.parametrize("color_theme", ["midnight-blue", "ember-sand"])
async def test_defaults_then_independent_partial_updates(api, color_theme):
    client, _ = api
    await tenant(client)
    assert await ok(client, "GET", "/v1/me/preferences") == {
        "color_theme": "classic-teal",
        "dashboard_style": "widgets",
    }
    # Changing one choice leaves the other alone, in either order.
    themed = await ok(client, "PATCH", "/v1/me/preferences", json={"color_theme": color_theme})
    assert themed == {"color_theme": color_theme, "dashboard_style": "widgets"}
    assert await ok(client, "GET", "/v1/me/preferences") == themed
    styled = await ok(client, "PATCH", "/v1/me/preferences", json={"dashboard_style": "overview"})
    assert styled == {"color_theme": color_theme, "dashboard_style": "overview"}
    back = await ok(client, "PATCH", "/v1/me/preferences", json={"color_theme": "classic-teal"})
    assert back == {"color_theme": "classic-teal", "dashboard_style": "overview"}
    assert await ok(client, "GET", "/v1/me/preferences") == back


@pytest.mark.parametrize(
    "body", [{"color_theme": "neon"}, {"dashboard_style": "grid"}, {"color_theme": 3}]
)
async def test_unknown_values_are_rejected(api, body):
    client, _ = api
    await tenant(client)
    assert (await client.patch("/v1/me/preferences", json=body)).status_code == 422


async def test_preferences_are_private_and_open_to_every_user(api):
    client, _ = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    await ok(client, "PATCH", "/v1/me/preferences", json={"dashboard_style": "overview"})

    email, _, _ = await make_user(client, role="HR_MANAGER", scope_type="ALL")
    hr = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": PASSWORD})
    hr_headers = {"Authorization": "Bearer " + hr["access_token"]}
    assert (await ok(client, "GET", "/v1/me/preferences", headers=hr_headers))[
        "dashboard_style"
    ] == "widgets"

    # A plain employee can pick a theme too.
    _, login = await employee(client, company)
    emp_headers = {"Authorization": "Bearer " + login["access_token"]}
    updated = await ok(
        client,
        "PATCH",
        "/v1/me/preferences",
        headers=emp_headers,
        json={"color_theme": "midnight-blue"},
    )
    assert updated["color_theme"] == "midnight-blue"
    assert (await ok(client, "GET", "/v1/me/preferences"))["color_theme"] == "classic-teal"

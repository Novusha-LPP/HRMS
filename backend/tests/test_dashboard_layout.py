"""Customisable HR dashboard: per-user layouts, the widget catalog, and section filtering."""

import pytest
from sqlalchemy import text

from hrms.core import database, perf
from hrms.core.ids import to_uuid
from hrms.modules.dashboard import widgets
from tests.helpers import employee, make_user, ok, tenant

pytestmark = pytest.mark.database

PASSWORD = "Test-password-123"
DEFAULT_IDS = [wid for wid, _ in widgets.DEFAULT_LAYOUT]


async def _login(client, email):
    r = await ok(client, "POST", "/v1/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": "Bearer " + r["access_token"]}


async def _hr(client, company, role="HR_MANAGER"):
    email, _, account = await make_user(
        client, role=role, scope_type="LEGAL_ENTITY", legal_entity_ids=[company]
    )
    return await _login(client, email), account


async def test_default_layout_is_the_classic_dashboard(api):
    client, _ = api
    await tenant(client)  # signed in as the company's SUPER_ADMIN, who may use every widget
    layout = await ok(client, "GET", "/v1/dashboard/layout")
    assert layout["is_default"] is True
    assert [w["widget"] for w in layout["widgets"]] == DEFAULT_IDS
    assert {w["id"] for w in layout["catalog"]} == {w.id for w in widgets.CATALOG}
    assert set(layout["sections"].split(",")) == widgets.sections_for(layout["widgets"])


async def test_save_reorder_resize_and_reset(api):
    client, _ = api
    await tenant(client)
    mine = [
        {"widget": "headcount_by_company", "size": "full"},
        {"widget": "kpi_headcount", "size": "third"},
        {"widget": "kyc_compliance", "size": "half"},
    ]
    saved = await ok(client, "PUT", "/v1/dashboard/layout", json={"widgets": mine})
    assert saved["widgets"] == mine and saved["is_default"] is False
    assert saved["sections"] == "headcount,entity_distribution,kyc"
    assert (await ok(client, "GET", "/v1/dashboard/layout"))["widgets"] == mine

    # Saving again replaces the layout rather than adding a second one.
    await ok(client, "PUT", "/v1/dashboard/layout", json={"widgets": mine[:1]})
    assert (await ok(client, "GET", "/v1/dashboard/layout"))["widgets"] == mine[:1]

    reset = await ok(client, "DELETE", "/v1/dashboard/layout")
    assert reset["is_default"] is True
    assert [w["widget"] for w in reset["widgets"]] == DEFAULT_IDS


@pytest.mark.parametrize(
    ("widgets_payload", "status"),
    [
        ([{"widget": "no_such_widget", "size": "half"}], 422),
        ([{"widget": "kpi_headcount", "size": "full"}], 422),  # KPI cards can't be full width
        ([{"widget": "kpi_headcount", "size": "gigantic"}], 422),
        ([{"widget": "kpi_headcount", "size": "quarter"}] * 2, 422),
        ([{"widget": "kpi_headcount", "size": "quarter"}] * 31, 422),
    ],
)
async def test_invalid_layouts_are_rejected(api, widgets_payload, status):
    client, _ = api
    await tenant(client)
    r = await client.put("/v1/dashboard/layout", json={"widgets": widgets_payload})
    assert r.status_code == status, r.text


async def test_widgets_follow_permissions(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    accountant, _ = await _hr(client, company, role="ACCOUNTANT")

    layout = await ok(client, "GET", "/v1/dashboard/layout", headers=accountant)
    offered = {w["id"] for w in layout["catalog"]}
    assert "leave_activity" not in offered and "approvals_queue" not in offered
    assert "kyc_compliance" in offered  # accountants have kyc.read
    assert "leave_activity" not in {w["widget"] for w in layout["widgets"]}

    r = await client.put(
        "/v1/dashboard/layout",
        headers=accountant,
        json={"widgets": [{"widget": "leave_activity", "size": "full"}]},
    )
    assert r.status_code == 403


async def test_a_saved_widget_disappears_when_access_is_lost(api):
    client, engine = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    hr, account = await _hr(client, company)
    await ok(
        client,
        "PUT",
        "/v1/dashboard/layout",
        headers=hr,
        json={
            "widgets": [
                {"widget": "leave_activity", "size": "half"},
                {"widget": "kpi_headcount", "size": "quarter"},
            ]
        },
    )
    async with engine.begin() as conn:
        await conn.execute(
            text("""UPDATE role_assignments ra SET role_id = r.id FROM roles r
                    WHERE r.tenant_id = ra.tenant_id AND r.name = 'ACCOUNTANT'
                      AND ra.user_account_id = :u"""),
            {"u": to_uuid(account["id"])},
        )
    layout = await ok(client, "GET", "/v1/dashboard/layout", headers=hr)
    assert layout["widgets"] == [{"widget": "kpi_headcount", "size": "quarter"}]


async def test_layouts_are_private_to_each_user(api):
    client, _ = api
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    hr_a, _ = await _hr(client, company)
    hr_b, _ = await _hr(client, company)
    await ok(
        client,
        "PUT",
        "/v1/dashboard/layout",
        headers=hr_a,
        json={"widgets": [{"widget": "tenure_mix", "size": "full"}]},
    )
    assert (await ok(client, "GET", "/v1/dashboard/layout", headers=hr_b))["is_default"] is True
    assert (await ok(client, "GET", "/v1/dashboard/layout"))["is_default"] is True  # the admin


async def test_employees_have_no_dashboard_layout(api):
    client, _ = api
    admin = await tenant(client)
    _, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    headers = {"Authorization": "Bearer " + login["access_token"]}
    assert (await client.get("/v1/dashboard/layout", headers=headers)).status_code == 403


async def test_dashboard_computes_only_requested_sections(api):
    client, _ = api
    await tenant(client)
    perf.instrument_engine(database.AsyncSessionLocal.kw["bind"])
    seen = []
    perf.REQUEST_OBSERVER = lambda scope, tally: seen.append(tally)
    try:
        some = await ok(client, "GET", "/v1/dashboard/hr?sections=headcount,kyc")
        few = seen[-1].count
        everything = await ok(client, "GET", "/v1/dashboard/hr")
        all_count = seen[-1].count
    finally:
        perf.REQUEST_OBSERVER = None
    assert set(some) == {"role", "scope", "headcount", "month", "kyc"}
    assert set(everything) >= {"headcount", "today", "actions", "org_summary", "kyc", "tenure"}
    assert few < all_count, (few, all_count)

    bad = await client.get("/v1/dashboard/hr?sections=headcount,salaries")
    assert bad.status_code == 422


def test_catalog_is_consistent():
    ids = [w.id for w in widgets.CATALOG]
    assert len(ids) == len(set(ids))
    for w in widgets.CATALOG:
        assert w.default_size in w.sizes and set(w.sizes) <= set(widgets.SIZES), w.id
        assert set(w.sections) <= set(widgets.SECTIONS), w.id
    for wid, size in widgets.DEFAULT_LAYOUT:
        assert size in widgets.BY_ID[wid].sizes, wid


async def test_overview_has_its_own_customisable_layout(api):
    client, _ = api
    await tenant(client)
    default = await ok(client, "GET", "/v1/dashboard/layout?dashboard=overview")
    ids = [w["widget"] for w in default["widgets"]]
    assert ids[0] == "attendance" and "training" in ids and default["is_default"]

    mine = [{"widget": "tasks", "size": "full"}, {"widget": "attendance", "size": "full"}]
    saved = await ok(
        client, "PUT", "/v1/dashboard/layout?dashboard=overview", json={"widgets": mine}
    )
    assert saved["widgets"] == mine
    # The widget grid's layout is untouched by the overview's.
    assert (await ok(client, "GET", "/v1/dashboard/layout"))["is_default"] is True

    bad = await client.put(
        "/v1/dashboard/layout?dashboard=overview",
        json={"widgets": [{"widget": "kpi_headcount", "size": "full"}]},
    )
    assert bad.status_code == 422


def test_overview_cards_ask_only_for_the_sections_they_show():
    from hrms.modules.dashboard import widgets

    # Every overview section must be one /v1/dashboard/hr knows.
    from hrms.modules.dashboard.router import SECTIONS

    for card in widgets.OVERVIEW_CATALOG:
        assert set(card.sections) <= set(SECTIONS), card.id
    assert widgets.sections_for([{"widget": "exits", "size": "full"}], "overview") == {"exits"}
    assert widgets.sections_for([{"widget": "quick_links", "size": "full"}], "overview") == set()

"""
The leave workflows that move balances: reject, cancel (with and without approval),
encashment, comp-off grants, manual adjustments and the year-end close. Every assertion is
on the balance the employee would see, not just the status code.
"""

from datetime import date, timedelta

import pytest

from tests.helpers import bearer, employee, make_user, ok, tenant

pytestmark = pytest.mark.database


def _next_weekday(start: date) -> date:
    day = start
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


async def _setup(client, **leave_type):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    emp, login = await employee(client, company)
    lt = await ok(
        client,
        "POST",
        "/v1/leave/types",
        json={
            "name": "Annual",
            "code": "AL",
            "days_per_year": 120,  # 10 days a month, so one accrual covers every test
            "accrual_enabled": True,
            **leave_type,
        },
    )
    await ok(client, "POST", "/v1/leave/accrual/run")
    return emp, bearer(login["access_token"]), lt


async def _balance(client, emp, lt):
    rows = await ok(client, "GET", f"/v1/leave/balances?employment_id={emp['id']}")
    return next(b for b in rows if b["leave_type_id"] == lt["id"])


async def _apply(client, header, lt, days=1):
    start = _next_weekday(date.today() + timedelta(days=7))
    end = start
    for _ in range(days - 1):
        end = _next_weekday(end + timedelta(days=1))
    app = await ok(
        client,
        "POST",
        "/v1/leave/applications",
        headers=header,
        json={"leave_type_id": lt["id"], "from_date": start.isoformat(),
              "to_date": end.isoformat()},
    )
    await ok(client, "POST", f"/v1/leave/applications/{app['id']}/submit", headers=header,
             json={})
    return app


async def test_rejection_releases_the_held_days(api):
    client, _ = api
    emp, header, lt = await _setup(client)
    before = await _balance(client, emp, lt)
    app = await _apply(client, header, lt, days=2)
    held = await _balance(client, emp, lt)
    assert held["pending_days"] == 2 and held["available_days"] == before["available_days"] - 2

    rejected = await ok(client, "POST", f"/v1/leave/applications/{app['id']}/reject",
                        json={"action": "REJECT", "comments": "Peak season"})
    assert rejected["status"] == "REJECTED"
    after = await _balance(client, emp, lt)
    assert after["pending_days"] == 0 and after["available_days"] == before["available_days"]
    # A decided application can't be decided again.
    again = await client.post(f"/v1/leave/applications/{app['id']}/approve",
                              json={"action": "APPROVE"})
    assert again.status_code in (400, 409)


async def test_cancelling_a_pending_application_needs_no_approval(api):
    client, _ = api
    emp, header, lt = await _setup(client)
    before = await _balance(client, emp, lt)
    app = await _apply(client, header, lt)
    cancelled = await ok(client, "POST", f"/v1/leave/applications/{app['id']}/cancel",
                         headers=header, json={"cancel_reason": "Not needed"})
    assert cancelled["status"] == "CANCELLED"
    assert (await _balance(client, emp, lt))["available_days"] == before["available_days"]


async def test_cancelling_approved_leave_can_require_approval_both_ways(api):
    client, _ = api
    emp, header, lt = await _setup(client, cancel_requires_approval=True)
    before = await _balance(client, emp, lt)

    # Cancellation refused: the leave stands and stays used.
    first = await _apply(client, header, lt)
    await ok(client, "POST", f"/v1/leave/applications/{first['id']}/approve",
             json={"action": "APPROVE"})
    pending = await ok(client, "POST", f"/v1/leave/applications/{first['id']}/cancel",
                       headers=header, json={"cancel_reason": "Trip moved"})
    assert pending["status"].startswith("CANCEL_PENDING")
    kept = await ok(client, "POST", f"/v1/leave/applications/{first['id']}/cancel-reject",
                    json={"action": "REJECT"})
    assert kept["status"] == "APPROVED"
    assert (await _balance(client, emp, lt))["used_days"] == 1

    # Cancellation approved — by a second HR reviewer: whoever approved the leave can't
    # also sign off its cancellation (separation of duties, modules/approvals).
    email, password, _ = await make_user(client, role="HR_MANAGER", scope_type="ALL")
    second = bearer((await ok(client, "POST", "/v1/auth/login",
                              json={"identifier": email, "password": password}))["access_token"])
    await ok(client, "POST", f"/v1/leave/applications/{first['id']}/cancel", headers=header,
             json={"cancel_reason": "Trip cancelled"})
    done = await ok(client, "POST", f"/v1/leave/applications/{first['id']}/cancel-approve",
                    headers=second, json={"action": "APPROVE"})
    assert done["status"] == "CANCELLED"
    after = await _balance(client, emp, lt)
    assert after["used_days"] == 0 and after["available_days"] == before["available_days"]


async def test_an_employee_cannot_decide_their_own_leave(api):
    client, _ = api
    _, header, lt = await _setup(client)
    app = await _apply(client, header, lt)
    r = await client.post(f"/v1/leave/applications/{app['id']}/approve", headers=header,
                          json={"action": "APPROVE"})
    assert r.status_code == 403


async def test_adjustments_move_the_balance_and_need_a_reason(api):
    client, _ = api
    emp, _, lt = await _setup(client)
    before = await _balance(client, emp, lt)
    body = {"employment_id": emp["id"], "leave_type_id": lt["id"], "quantity": 3,
            "reason": "Joining bonus"}
    added = await ok(client, "POST", "/v1/leave/balances/adjust", json=body)
    assert added["new_balance"] == pytest.approx(before["available_days"] + 3)
    removed = await ok(client, "POST", "/v1/leave/balances/adjust",
                       json={**body, "quantity": -1, "reason": "Correction"})
    assert removed["new_balance"] == pytest.approx(before["available_days"] + 2)
    no_reason = await client.post("/v1/leave/balances/adjust", json={**body, "reason": ""})
    assert no_reason.status_code == 422


async def test_encashment_pays_out_only_what_is_there(api):
    client, _ = api
    emp, _, lt = await _setup(client, encashable=True)
    before = await _balance(client, emp, lt)
    paid = await ok(client, "POST", "/v1/leave/encashment",
                    json={"employment_id": emp["id"], "leave_type_id": lt["id"], "days": 2})
    assert paid["days"] == 2
    assert (await _balance(client, emp, lt))["available_days"] == pytest.approx(
        before["available_days"] - 2
    )
    too_much = await client.post(
        "/v1/leave/encashment",
        json={"employment_id": emp["id"], "leave_type_id": lt["id"], "days": 999},
    )
    assert too_much.status_code in (400, 409, 422)


async def test_a_type_that_is_not_encashable_refuses_encashment(api):
    client, _ = api
    emp, _, lt = await _setup(client)
    r = await client.post("/v1/leave/encashment",
                          json={"employment_id": emp["id"], "leave_type_id": lt["id"], "days": 1})
    assert r.status_code in (400, 409, 422)


async def test_comp_off_credits_the_comp_off_type(api):
    client, _ = api
    emp, _, _ = await _setup(client)
    comp = await ok(client, "POST", "/v1/leave/types",
                    json={"name": "Comp off", "code": "CO", "days_per_year": 0,
                          "is_comp_off": True})
    worked = date.today() - timedelta(days=3)
    grant = await ok(client, "POST", "/v1/leave/comp-off",
                     json={"employment_id": emp["id"], "work_date": worked.isoformat(),
                           "days_granted": 1})
    assert grant["days_granted"] == 1 and grant["work_date"] == worked.isoformat()
    assert (await _balance(client, emp, comp))["available_days"] >= 1


async def test_year_end_close_caps_the_carry_forward(api):
    client, _ = api
    emp, _, lt = await _setup(client, carry_forward=True, max_carry_forward_days=4)
    # The financial year label of today's ledger rows (April start by default).
    today = date.today()
    fy = today.year if today.month >= 4 else today.year - 1
    closed = await ok(client, "POST", f"/v1/leave/year-end-close?fy_year={fy}")
    assert closed["fy_year"] == fy and closed["buckets_closed"] >= 1
    # 10 days credited, at most 4 carried: at least 6 lapse.
    assert closed["days_lapsed"] >= 6
    # Closing the same year again changes nothing.
    again = await ok(client, "POST", f"/v1/leave/year-end-close?fy_year={fy}")
    assert again["days_lapsed"] == 0

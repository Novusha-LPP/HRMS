"""Account lifecycle and login hardening, exercised through the real app on PostgreSQL."""

import asyncio
import json
import time
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text

from hrms.core.config import settings
from tests.helpers import (
    PASSWORD,
    bearer,
    client_from,
    hire,
    make_user,
    ok,
    org_basics,
    person_and_employment,
    sign_in,
    tenant,
)

pytestmark = pytest.mark.database


async def _placed_employee_with_login(client, legal_entity, placement, **user_kwargs):
    emp = await person_and_employment(client, legal_entity)
    await hire(client, emp["id"], placement)
    email, password, created = await make_user(client, emp["id"], **user_kwargs)
    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    return emp, email, password, created, bearer(login["access_token"])


# ─── Offboarding ─────────────────────────────────────────────────────────────


async def test_separated_employee_loses_access_and_rehire_restores_it(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    emp, email, password, _, token = await _placed_employee_with_login(client, le, placement)
    assert (await client.get("/v1/auth/me", headers=token)).status_code == 200

    await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "SEPARATION",
            "effective_date": str(date.today()),
            "reason_code": "RESIGNATION",
        },
    )

    # The token they already hold stops working at once, on any endpoint …
    assert (await client.get("/v1/auth/me", headers=token)).status_code == 401
    punch = await client.post("/v1/time/punches", headers=token, json={"punch_type": "IN"})
    assert punch.status_code == 401
    # … and they cannot sign in again, even with the right password.
    refused = await sign_in(client, email, password)
    assert refused.status_code == 403 and "no longer active" in refused.json()["detail"]
    # The admin can see why: the account is ACTIVE but cannot sign in.
    mine = next(u for u in await ok(client, "GET", "/v1/users") if u["email"] == email)
    assert (mine["status"], mine["employment_state"], mine["can_sign_in"]) == (
        "ACTIVE",
        "SEPARATED",
        False,
    )

    await ok(
        client,
        "POST",
        "/v1/personnel-actions",
        json={
            "employment_id": emp["id"],
            "type": "REHIRE",
            "effective_date": str(date.today()),
            "changes": placement,
        },
    )
    assert (await sign_in(client, email, password)).status_code == 200


async def test_admin_can_deactivate_and_reactivate_a_login(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    _, email, password, created, token = await _placed_employee_with_login(client, le, placement)

    off = await ok(client, "PATCH", f"/v1/users/{created['id']}", json={"status": "INACTIVE"})
    assert off["status"] == "INACTIVE" and off["can_sign_in"] is False
    assert (await client.get("/v1/auth/me", headers=token)).status_code == 401
    assert (await sign_in(client, email, password)).status_code == 401
    on = await ok(client, "PATCH", f"/v1/users/{created['id']}", json={"status": "ACTIVE"})
    assert on["can_sign_in"] is True
    assert (await sign_in(client, email, password)).status_code == 200

    # You can't lock yourself out …
    mine = await client.patch(f"/v1/users/{admin['user']['id']}", json={"status": "INACTIVE"})
    assert mine.status_code == 400


async def test_managing_logins_cannot_escalate_or_cross_companies(api):
    client, _ = api
    admin = await tenant(client)
    company_a = admin["user"]["legal_entities"][0]["id"]
    company_b = (
        await ok(client, "POST", "/v1/org/legal-entities", json={"name": "B", "country_code": "IN"})
    )["id"]
    pa, pb = await org_basics(client, company_a), await org_basics(client, company_b)
    _, _, _, in_a, _ = await _placed_employee_with_login(client, company_a, pa)
    _, _, _, in_b, _ = await _placed_employee_with_login(client, company_b, pb)
    hr_email, hr_pw, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[company_a]
    )
    hr = bearer(
        (
            await ok(
                client, "POST", "/v1/auth/login", json={"identifier": hr_email, "password": hr_pw}
            )
        )["access_token"]
    )

    # A company HR manager manages their own company's logins …
    assert (
        await client.patch(f"/v1/users/{in_a['id']}", headers=hr, json={"status": "INACTIVE"})
    ).status_code == 200
    # … but not another company's, and never the group administrator's.
    assert (
        await client.patch(f"/v1/users/{in_b['id']}", headers=hr, json={"status": "INACTIVE"})
    ).status_code == 403
    assert (
        await client.patch(
            f"/v1/users/{admin['user']['id']}", headers=hr, json={"status": "INACTIVE"}
        )
    ).status_code == 403
    takeover = await client.post(
        f"/v1/users/{admin['user']['id']}/reset-password",
        headers=hr,
        json={"password": "Attacker-pass-1"},
    )
    assert takeover.status_code == 403
    # The refused takeover changed nothing: the administrator's own password still works.
    assert (await sign_in(client, admin["user"]["email"], PASSWORD)).status_code == 200


# ─── Passwords ───────────────────────────────────────────────────────────────


async def test_reset_forces_change_ends_sessions_and_change_password_works(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    _, email, _, created, old_token = await _placed_employee_with_login(client, le, placement)

    reset = await ok(
        client,
        "POST",
        f"/v1/users/{created['id']}/reset-password",
        json={"password": "Temp-pass-9999"},
    )
    assert reset["must_change_password"] is True
    # Every session that existed before the reset is over.
    revoked = await client.get("/v1/auth/me", headers=old_token)
    assert revoked.status_code == 401 and "password was changed" in revoked.json()["detail"]

    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": "Temp-pass-9999"}
    )
    assert login["user"]["must_change_password"] is True
    temp = bearer(login["access_token"])
    # Until the password is changed, everything except /me and change-password is refused.
    blocked = await client.get("/v1/employees", headers=temp)
    assert blocked.status_code == 403 and blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert (await client.get("/v1/auth/me", headers=temp)).status_code == 200

    def change(current, new):
        return client.post(
            "/v1/auth/change-password",
            headers=temp,
            json={"current_password": current, "new_password": new},
        )

    assert (await change("wrong-current-1", "Brand-new-pass-1")).status_code == 400
    assert (await change("Temp-pass-9999", "Temp-pass-9999")).status_code == 400
    assert (await change("Temp-pass-9999", "😀" * 30)).status_code == 422  # 120 bytes > bcrypt's 72
    changed = await ok(
        client,
        "POST",
        "/v1/auth/change-password",
        headers=temp,
        json={"current_password": "Temp-pass-9999", "new_password": "Brand-new-pass-1"},
    )
    assert changed["user"]["must_change_password"] is False
    fresh = bearer(changed["access_token"])

    # The temporary password and the token that carried it are dead; the new pair works.
    assert (await client.get("/v1/auth/me", headers=temp)).status_code == 401
    assert (await sign_in(client, email, "Temp-pass-9999")).status_code == 401
    assert (await client.get("/v1/employees", headers=fresh)).status_code == 200
    assert (await sign_in(client, email, "Brand-new-pass-1")).status_code == 200


async def test_password_too_long_in_bytes_is_a_validation_error_not_a_500(api):
    client, _ = api
    response = await client.post(
        "/v1/auth/register-company",
        json={
            "company_name": "Emoji Co",
            "admin_email": uuid4().hex + "@example.com",
            "admin_password": "😀" * 30,
        },
    )
    assert response.status_code == 422


async def test_imported_accounts_flagged_for_change_are_forced_through_it(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    emp = await person_and_employment(client, le)
    await hire(client, emp["id"], placement)
    email, password, _ = await make_user(client, emp["id"], must_change_password=True)
    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    assert login["user"]["must_change_password"] is True
    assert (
        await client.get("/v1/time/today", headers=bearer(login["access_token"]))
    ).status_code == 403


# ─── Login: throttling, ambiguity, formats, timing ───────────────────────────


async def test_login_locks_out_after_repeated_failures(api):
    client, engine = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    email, password, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    async with client_from("10.9.8.7") as attacker:
        for _ in range(settings.login_max_failures):
            assert (await sign_in(attacker, email, "wrong-password-1")).status_code == 401
        locked = await sign_in(attacker, email, password)  # even the RIGHT password
        assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    async with client_from("10.9.8.8") as elsewhere:  # the real user isn't locked out by it
        assert (await sign_in(elsewhere, email, password)).status_code == 200
    async with engine.begin() as conn:  # the lockout lapses
        await conn.execute(text("UPDATE auth_throttle SET locked_until = now() - interval '1 s'"))
    async with client_from("10.9.8.7") as again:
        assert (await sign_in(again, email, password)).status_code == 200


async def test_anonymous_registration_is_rate_limited_and_can_be_disabled(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(settings, "register_max_per_hour", 2)

    def register(c):
        return c.post(
            "/v1/auth/register-company",
            json={
                "company_name": "Spam " + uuid4().hex[:6],
                "admin_email": uuid4().hex + "@example.com",
                "admin_password": PASSWORD,
            },
        )

    async with client_from("10.20.30.40") as spammer:
        assert (await register(spammer)).status_code == 201
        assert (await register(spammer)).status_code == 201
        assert (await register(spammer)).status_code == 429
    async with client_from("10.20.30.41") as other:
        assert (await register(other)).status_code == 201
    monkeypatch.setattr(settings, "allow_public_registration", False)
    async with client_from("10.20.30.42") as closed:
        assert (await register(closed)).status_code == 403


async def _set_login_fields(engine, email, **fields):
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE user_accounts SET {sets} WHERE email = :email"),
            {"email": email, **fields},
        )


async def test_ambiguous_identifiers_are_settled_by_password_not_guessed(api):
    client, engine = api
    first, second = await tenant(client), await tenant(client)
    accounts = []
    for company, pw in ((first, "First-company-pw-1"), (second, "Second-company-pw-2")):
        headers = bearer(company["access_token"])
        le = company["user"]["legal_entities"][0]["id"]
        email, _, _ = await make_user(
            client,
            role="HR_MANAGER",
            scope_type="LEGAL_ENTITY",
            legal_entity_ids=[le],
            headers=headers,
            password=pw,
        )
        accounts.append((company, email, pw))
    # The same employee code and the same mobile number exist in both companies.
    for _, email, _ in accounts:
        await _set_login_fields(engine, email, employee_code="EMP-1", mobile="9000000001")

    for company, _, pw in accounts:
        for identifier in ("emp-1", "EMP-1", "+91 90000 00001", "9000000001"):
            r = await sign_in(client, identifier, pw)
            assert r.status_code == 200, (identifier, r.text)
            assert r.json()["user"]["tenant_id"] == company["user"]["tenant_id"]
    assert (await sign_in(client, "EMP-1", "neither-password-1")).status_code == 401

    # An inactive namesake never shadows the live account.
    _, first_email, first_pw = accounts[0]
    _, second_email, second_pw = accounts[1]
    await _set_login_fields(engine, second_email, status="INACTIVE")
    assert (await sign_in(client, "EMP-1", first_pw)).status_code == 200
    assert (await sign_in(client, "EMP-1", second_pw)).status_code == 401


async def test_login_accepts_email_employee_code_and_mobile_in_any_format(api):
    client, engine = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    email, password, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    await _set_login_fields(engine, email, employee_code="RI_014", mobile="9876543210")

    for payload in (
        {"identifier": email.upper()},
        {"identifier": "  " + email + "  "},
        {"identifier": "ri_014"},
        {"identifier": "9876543210"},
        {"identifier": "+919876543210"},
        {"identifier": "+91 98765 43210"},
        {"identifier": "098765-43210"},
        {"email": "9876543210"},  # legacy payload shapes
        {"username": "RI_014"},
        {"phone": "+919876543210"},
    ):
        r = await client.post("/v1/auth/login", json={**payload, "password": password})
        assert r.status_code == 200, (payload, r.text)
    for wrong in ("9876543211", "RI_015", "someone@example.com", "   "):
        assert (await sign_in(client, wrong, password)).status_code in (401, 422), wrong
    assert (await sign_in(client, "RI_014", "not-the-password")).status_code == 401


async def test_unknown_and_wrong_password_are_indistinguishable(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    email, _, _ = await make_user(
        client, role="HR_MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    timings, bodies = {}, {}
    for label, identifier in (
        ("unknown", "nobody-" + uuid4().hex[:6] + "@example.com"),
        ("known", email),
    ):
        started = time.perf_counter()
        r = await sign_in(client, identifier, "definitely-wrong-1")
        timings[label], bodies[label] = time.perf_counter() - started, (r.status_code, r.json())
    # Every error body carries this request's own id and time; apart from those two, the
    # responses must be byte-for-byte the same.
    for _status, body in bodies.values():
        body.pop("request_id", None)
        for per_request in ("request_id", "timestamp"):
            body.get("error", {}).pop(per_request, None)
    assert bodies["unknown"] == bodies["known"]
    assert bodies["known"][0] == 401 and bodies["known"][1]["detail"] == "Invalid credentials"
    # A miss must spend a real password-check's time (bcrypt ≈ 0.1–0.3 s), otherwise
    # response time reveals which identifiers exist. 0.05 s only guards its removal.
    assert timings["unknown"] > 0.05


async def test_password_checks_do_not_freeze_the_event_loop(api):
    client, _ = api
    await tenant(client)
    lags: list[float] = []
    stop = asyncio.Event()

    async def ticker():
        while not stop.is_set():
            started = time.perf_counter()
            await asyncio.sleep(0.005)
            lags.append(time.perf_counter() - started - 0.005)

    watcher = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)
    await asyncio.gather(
        *[sign_in(client, f"nobody{i}@example.com", "x-wrong-1") for i in range(6)]
    )
    stop.set()
    await watcher
    # bcrypt on the loop would stall it ~0.17 s per check (≈1 s for six); off-loop it stays ≪ that.
    assert max(lags) < 0.25, f"event loop stalled for {max(lags):.3f}s"


# ─── Roles and scopes ────────────────────────────────────────────────────────


async def test_employee_role_is_self_service_whatever_scope_is_stored(api):
    client, engine = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    emps = []
    for _ in range(3):
        e = await person_and_employment(client, le, date_of_birth="1990-05-05", gender="F")
        await hire(client, e["id"], placement)
        emps.append(e)

    # The API refuses to create the contradictory grant …
    refused = await client.post(
        "/v1/users",
        json={
            "email": uuid4().hex + "@example.com",
            "password": PASSWORD,
            "role": "EMPLOYEE",
            "scope_type": "LEGAL_ENTITY",
            "legal_entity_ids": [le],
            "employment_id": emps[0]["id"],
        },
    )
    assert refused.status_code == 400

    # … and data that already holds it (an import that gave every account a company scope)
    # still resolves to "own record only".
    email, password, _ = await make_user(client, emps[0]["id"])
    async with engine.begin() as conn:
        await conn.execute(
            text("""UPDATE role_assignments SET scope_type = 'LEGAL_ENTITY', scope_value = :v
                    WHERE user_account_id = (SELECT id FROM user_accounts WHERE email = :e)"""),
            {"v": json.dumps([le]), "e": email},
        )
    login = await ok(
        client, "POST", "/v1/auth/login", json={"identifier": email, "password": password}
    )
    token = bearer(login["access_token"])
    assert login["user"]["is_all_scope"] is False and login["user"]["legal_entities"][0]["id"] == le
    listed = await ok(client, "GET", "/v1/employees", headers=token)
    assert [e["id"] for e in listed] == [emps[0]["id"]]
    persons = await ok(client, "GET", "/v1/persons", headers=token)
    assert len(persons) == 1
    assert (await client.get(f"/v1/employees/{emps[1]['id']}", headers=token)).status_code == 403


async def test_date_of_birth_and_gender_are_visible_to_hr_and_the_person_only(api):
    client, _ = api
    admin = await tenant(client)
    le = admin["user"]["legal_entities"][0]["id"]
    placement = await org_basics(client, le)
    subject = await person_and_employment(client, le, date_of_birth="1988-02-03", gender="M")
    await hire(client, subject["id"], placement)
    boss = await person_and_employment(client, le)
    await hire(client, boss["id"], placement)
    mgr_email, mgr_pw, _ = await make_user(
        client, boss["id"], role="MANAGER", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    acct_email, acct_pw, _ = await make_user(
        client, role="ACCOUNTANT", scope_type="LEGAL_ENTITY", legal_entity_ids=[le]
    )
    own_email, own_pw, _ = await make_user(client, subject["id"])

    async def view_as(email, pw):
        token = bearer(
            (
                await ok(
                    client, "POST", "/v1/auth/login", json={"identifier": email, "password": pw}
                )
            )["access_token"]
        )
        detail = await ok(client, "GET", f"/v1/employees/{subject['id']}", headers=token)
        listing = {e["id"]: e for e in await ok(client, "GET", "/v1/employees", headers=token)}
        persons = {p["id"]: p for p in await ok(client, "GET", "/v1/persons", headers=token)}
        return detail, listing.get(subject["id"]), persons.get(subject["person_id"])

    for who in (view_as(mgr_email, mgr_pw), view_as(acct_email, acct_pw)):
        detail, listed, person = await who
        assert detail["date_of_birth"] is None and detail["gender"] is None
        assert listed["date_of_birth"] is None and person["date_of_birth"] is None
        assert detail["full_name"]  # names stay visible: people.read is for "who works where"
    for who in (view_as(own_email, own_pw),):
        detail, listed, person = await who
        assert detail["date_of_birth"] == "1988-02-03" and person["gender"] == "M"
    hr = await ok(client, "GET", f"/v1/employees/{subject['id']}")
    assert hr["date_of_birth"] == "1988-02-03" and hr["gender"] == "M"

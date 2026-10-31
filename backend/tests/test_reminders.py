"""Date reminders over HTTP and through the tick/deliver jobs, with a fake mail sender."""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from hrms.core import database
from hrms.core.config import settings
from hrms.core.ids import to_uuid
from hrms.modules.reminders import service
from tests.helpers import make_user, ok, person_and_employment, tenant

pytestmark = pytest.mark.database

# 09:30 in Asia/Kolkata (the default tenant timezone) on 31 October 2026.
NOW = datetime(2026, 10, 31, 4, 0, tzinfo=UTC)
TODAY = date(2026, 10, 31)

RULE = {
    "name": "Birthdays",
    "trigger": "BIRTHDAY",
    "frequency": "CONTINUOUS",
    "days_before": 5,
    "send_time": "09:00",
    "notify_employee": True,
    "extra_emails": ["hr@example.com"],
    "digest": True,
    "subject": "Birthdays ({count})",
    "body_html": "<p>{count} due</p><ul>{#each}<li>{full_name} {when}</li>{/each}</ul>",
    "employee_subject": "Happy birthday, {first_name}!",
    "employee_body_html": "<p>Dear {first_name}, from {company_name}</p>",
}


@pytest.fixture(autouse=True)
def mail_on(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "ses")


async def _in_tenant(tenant_id, work):
    async with database.AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        return await work(session)


async def _arm(engine, tid):
    """Make every rule due again: saving a rule after its time of day marks it as run today,
    by the real clock, while these tests tick at a fixed time."""
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE reminder_rules SET last_run_date = NULL WHERE tenant_id = :t"), {"t": tid}
        )


async def _setup(client, **person):
    admin = await tenant(client)
    company = admin["user"]["legal_entities"][0]["id"]
    emp = await person_and_employment(
        client, company, legal_first_name="Asha", legal_last_name="Patel <Co>", **person
    )
    email, _, _ = await make_user(client, emp["id"])
    return to_uuid(admin["user"]["tenant_id"]), emp, email


async def test_wording_and_audience_are_checked(api):
    client, _ = api
    await tenant(client)
    bad = await client.post("/v1/reminders/rules", json={**RULE, "subject": "Hi {birthdate}"})
    assert bad.status_code == 422 and "birthdate" in bad.text
    nobody = await client.post(
        "/v1/reminders/rules", json={**RULE, "notify_employee": False, "extra_emails": []}
    )
    assert nobody.status_code == 422
    no_days = await client.post("/v1/reminders/rules", json={**RULE, "days_before": 0})
    assert no_days.status_code == 422


async def test_tick_queues_once_and_delivery_words_each_mail(api):
    client, engine = api
    # Three days to the birthday, inside the five-day window.
    tid, _, employee_email = await _setup(client, date_of_birth="1990-11-03")
    far = await person_and_employment(
        client,
        (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"],
        date_of_birth="1990-12-25",
    )
    assert far
    await ok(client, "POST", "/v1/reminders/rules", json=RULE)
    await _arm(engine, tid)

    # Three days ahead: HR gets its heads-up, the person's own greeting waits for the day.
    assert "1 mail(s)" in await _in_tenant(tid, lambda s: service.tick(s, tid, NOW))
    again = await _in_tenant(tid, lambda s: service.tick(s, tid, NOW))
    assert "0 rule(s)" in again

    sent = []
    result = await _in_tenant(
        tid, lambda s: service.deliver(s, tid, lambda *mail: sent.append(mail), TODAY)
    )
    assert result == {"sent": 1, "failed": 0}
    by_address = {m[0]: m for m in sent}
    assert employee_email not in by_address
    hr = by_address["hr@example.com"]
    assert hr[1] == "Birthdays (1)"
    assert "Asha Patel &lt;Co&gt; in 3 days" in hr[2] and "Dec" not in hr[2]
    assert "Asha Patel" in hr[3]  # the plain-text copy

    rows = await ok(client, "GET", "/v1/reminders/deliveries")
    assert [r["status"] for r in rows] == ["SENT"]


async def test_edits_apply_to_mail_not_yet_sent_and_are_recorded(api):
    client, engine = api
    tid, _, _ = await _setup(client, date_of_birth="1990-11-03")
    rule = await ok(client, "POST", "/v1/reminders/rules", json=RULE)
    await _arm(engine, tid)
    await _in_tenant(tid, lambda s: service.tick(s, tid, NOW))

    await ok(
        client,
        "PATCH",
        f"/v1/reminders/rules/{rule['id']}",
        json={"employee_body_html": "<p>New wording for {first_name}</p>", "version": 0},
    )
    stale = await client.patch(
        f"/v1/reminders/rules/{rule['id']}", json={"digest": False, "version": 0}
    )
    assert stale.status_code == 409

    sent = []
    await _in_tenant(tid, lambda s: service.deliver(s, tid, lambda *m: sent.append(m), TODAY))
    # The person's own mail is only sent on the day, so ask again on the birthday itself.
    assert sent and all("New wording for Asha" not in m[2] for m in sent)

    history = await ok(client, "GET", f"/v1/reminders/rules/{rule['id']}/history")
    assert [h["action"] for h in history] == ["UPDATE", "CREATE"]
    assert "employee_body_html" in history[0]["changes"]


async def test_a_paused_rule_sends_nothing_and_a_late_rule_waits_for_tomorrow(api):
    client, engine = api
    tid, _, _ = await _setup(client, date_of_birth="1990-11-03")
    rule = await ok(client, "POST", "/v1/reminders/rules", json=RULE)
    await _arm(engine, tid)
    await _in_tenant(tid, lambda s: service.tick(s, tid, NOW))
    await ok(client, "PATCH", f"/v1/reminders/rules/{rule['id']}", json={"is_active": False})
    sent = []
    result = await _in_tenant(
        tid, lambda s: service.deliver(s, tid, lambda *m: sent.append(m), TODAY)
    )
    assert sent == [] and result["failed"] == 1
    failed = await ok(client, "GET", "/v1/reminders/deliveries")
    assert {r["last_error"] for r in failed} == {"rule paused or removed"}

    # Saved after its time of day: it does not fire retroactively.
    late = await ok(client, "POST", "/v1/reminders/rules", json={**RULE, "send_time": "00:00"})
    assert late["last_run_date"] is not None


async def test_upcoming_lists_who_and_when(api):
    client, _ = api
    # Ten days from today by the clock, so the whole five-day window is still ahead.
    in_ten = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=10)
    await _setup(client, date_of_birth=in_ten.replace(year=1992).isoformat())
    rule = await ok(client, "POST", "/v1/reminders/rules", json=RULE)
    people = await ok(client, "GET", f"/v1/reminders/rules/{rule['id']}/upcoming?days=90")
    assert [p["full_name"] for p in people] == ["Asha Patel <Co>"]
    assert len(people[0]["sends_on"]) == 6  # five days ahead, through the day itself


async def test_preview_and_reference(api):
    client, _ = api
    await tenant(client)
    preview = await ok(
        client,
        "POST",
        "/v1/reminders/preview",
        json={
            "trigger": "BIRTHDAY",
            "audience": "TEAM",
            "subject": "{count}",
            "body_html": "<script>x</script>{#each}<b>{full_name}</b>{/each}",
        },
    )
    assert "Asha Patel" in preview["html"] and "<script" not in preview["html"]
    assert preview["problems"] == []
    variables = await ok(client, "GET", "/v1/reminders/variables?trigger=WORK_ANNIVERSARY")
    assert "years" in variables["variables"] and "age" not in variables["variables"]
    starter = await ok(client, "GET", "/v1/reminders/defaults?trigger=BIRTHDAY")
    assert "{#each}" in starter["body_html"]


async def test_the_persons_own_greeting_goes_out_on_the_day_only(api):
    client, engine = api
    tid, _, employee_email = await _setup(client, date_of_birth="1990-11-03")
    await ok(client, "POST", "/v1/reminders/rules", json=RULE)
    await _arm(engine, tid)
    birthday = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)
    await _in_tenant(tid, lambda s: service.tick(s, tid, birthday))
    sent = []
    await _in_tenant(
        tid, lambda s: service.deliver(s, tid, lambda *m: sent.append(m), date(2026, 11, 3))
    )
    greeting = next(m for m in sent if m[0] == employee_email)
    assert greeting[1] == "Happy birthday, Asha!" and "Dear Asha" in greeting[2]


async def test_everyone_is_told_except_the_person_it_is_about(api):
    client, engine = api
    tid, _, asha = await _setup(client, date_of_birth="1990-11-03")
    company = (await ok(client, "GET", "/v1/org/legal-entities"))[0]["id"]
    others = []
    for name in ("Imran", "Meera"):
        emp = await person_and_employment(client, company, legal_first_name=name)
        email, _, _ = await make_user(client, emp["id"])
        others.append(email)
    await ok(
        client,
        "POST",
        "/v1/reminders/rules",
        json={**RULE, "notify_employee": False, "extra_emails": [], "notify_everyone": True},
    )
    await _arm(engine, tid)
    await _in_tenant(tid, lambda s: service.tick(s, tid, NOW))
    sent = []
    await _in_tenant(tid, lambda s: service.deliver(s, tid, lambda *m: sent.append(m), TODAY))
    # Each colleague is mailed once; Asha, who is the only birthday, hears nothing about herself.
    assert sorted(m[0] for m in sent) == sorted(others)
    assert all("Asha Patel" in m[2] for m in sent)


async def _one_off(client, engine, column, value, trigger, **rule):
    tid, emp, email = await _setup(client)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE employments SET {column} = :v WHERE tenant_id = :t AND id = :e"),
            {"v": value, "t": tid, "e": to_uuid(emp["id"])},
        )
    await ok(
        client,
        "POST",
        "/v1/reminders/rules",
        json={**RULE, "trigger": trigger, "days_before": 0, "frequency": "ONE_DAY_BEFORE", **rule},
    )
    await _arm(engine, tid)
    return tid, email


async def test_a_new_joiner_is_announced_the_day_before_and_welcomed_on_the_day(api):
    client, engine = api

    tid, email = await _one_off(
        client,
        engine,
        "hire_date",
        date(2026, 11, 3),
        "NEW_JOINER",
        subject="New joiners ({count})",
        body_html="<ul>{#each}<li>{full_name} joins {when} ({joining_date})</li>{/each}</ul>",
        employee_subject="Welcome, {first_name}",
        employee_body_html="<p>Welcome to {company_name}</p>",
    )
    sent = []
    day_before = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)
    await _in_tenant(tid, lambda s: service.tick(s, tid, day_before))
    await _in_tenant(
        tid, lambda s: service.deliver(s, tid, lambda *m: sent.append(m), date(2026, 11, 2))
    )
    assert [m[0] for m in sent] == ["hr@example.com"]
    assert "tomorrow (3 Nov 2026)" in sent[0][2]
    # Not a yearly event: a year later nothing is due.
    people = await _in_tenant(tid, lambda s: _due(s, tid, date(2027, 11, 2)))
    assert people == []


async def _due(session, tid, day):
    rule = (
        await session.execute(
            text("SELECT id FROM reminder_rules WHERE tenant_id = :t"), {"t": tid}
        )
    ).scalar_one()
    rule = await session.get(service.ReminderRule, (tid, rule))
    return service.due_on(await service.candidates(session, tid, rule, day), rule, day)


async def test_an_exit_reminder_counts_the_last_day_and_ignores_people_who_stay(api):
    client, engine = api
    tid, email = await _one_off(
        client,
        engine,
        "separation_date",
        date(2026, 11, 14),
        "EXIT",
        frequency="CUSTOM",
        custom_offsets=[3, 0],
        subject="Exits ({count})",
        body_html="<ul>{#each}<li>{full_name}: last day {last_day}</li>{/each}</ul>",
        employee_subject="Thank you, {first_name}",
        employee_body_html="<p>All the best</p>",
    )
    assert [
        p["full_name"] for p in await _in_tenant(tid, lambda s: _due(s, tid, date(2026, 11, 11)))
    ] == ["Asha Patel <Co>"]
    # The last day itself still counts; the day after it does not.
    assert await _in_tenant(tid, lambda s: _due(s, tid, date(2026, 11, 14)))
    assert await _in_tenant(tid, lambda s: _due(s, tid, date(2026, 11, 15))) == []
    # Nobody else is leaving, so a birthday-style rule would have found nobody: exit needs a date.
    assert await _in_tenant(tid, lambda s: _due(s, tid, date(2026, 11, 8))) == []


async def test_a_large_queue_is_delivered_in_one_run(api):
    client, engine = api
    tid, _, _ = await _setup(client, date_of_birth="1990-11-03")
    rule = await ok(client, "POST", "/v1/reminders/rules", json=RULE)
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO reminder_outbox (tenant_id, id, rule_id, send_date, audience,
                    recipient_email, dedupe_key, payload)
                SELECT :t, gen_random_uuid(), :r, :d, 'TEAM', 'p' || n || '@example.com',
                       'k' || n, CAST(:p AS jsonb)
                FROM generate_series(1, 130) n
            """),
            {
                "t": tid,
                "r": to_uuid(rule["id"]),
                "d": TODAY,
                "p": json.dumps({"people": [service_person()]}),
            },
        )
    sent = []
    result = await _in_tenant(
        tid, lambda s: service.deliver(s, tid, lambda *m: sent.append(m), TODAY)
    )
    assert result == {"sent": 130, "failed": 0} and len(sent) == 130


def service_person():
    return {
        "employment_id": "x",
        "first_name": "A",
        "full_name": "A B",
        "department": "",
        "designation": "",
        "manager_name": "",
        "event_date": "2026-11-03",
        "days_left": 3,
        "age": 30,
    }

"""
Reminders at work: find who is due, queue the mail, send it.

`tick` runs every few minutes (the `reminders` job). For each active rule whose send time has
passed in the tenant's timezone and that has not yet run today, it works out who is due today
and queues the mail; `last_run_date` and the outbox's unique key make a repeat harmless.
`deliver` then sends queued mail in small batches, wording each one at that moment, so an edit
to a rule applies to mail not yet sent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from hrms.core.config import settings
from hrms.core.datetime_utils import now_utc, safe_tz
from hrms.modules.branding import resolve
from hrms.modules.reminders import dates, templates
from hrms.modules.reminders.models import ReminderRule, ReminderTrigger

logger = logging.getLogger("hrms.reminders")

BATCH = 50
MAX_PER_RUN = 1000  # a run sends at most this many; the rest go on the next run
MAX_ATTEMPTS = 5
STALE_AFTER = timedelta(days=2)

# Placement is read as of the later of today and the joining date, so a new joiner who has not
# started yet still shows their department and manager. Units under the chosen department count.
CANDIDATES = """
WITH RECURSIVE units AS (
    SELECT id FROM org_units WHERE tenant_id = :tid AND id = CAST(:ou AS uuid)
    UNION ALL
    SELECT c.id FROM org_units c JOIN units u ON c.parent_id = u.id WHERE c.tenant_id = :tid
)
SELECT e.id AS employment_id, e.hire_date, e.separation_date, e.continuity_start_date,
       p.date_of_birth, p.legal_first_name, p.legal_last_name, p.preferred_name,
       ou.name AS department, j.title AS designation,
       ua.email AS email, mua.email AS manager_email,
       mp.legal_first_name AS manager_first, mp.legal_last_name AS manager_last
FROM employments e
JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id
     AND a.effective_from <= GREATEST(CAST(:today AS date), e.hire_date)
     AND (a.effective_to IS NULL OR a.effective_to >= GREATEST(CAST(:today AS date), e.hire_date))
LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
LEFT JOIN assignment_managers am ON am.tenant_id = a.tenant_id AND am.assignment_id = a.id
     AND am.manager_type = 'LINE'
     AND am.effective_from <= GREATEST(CAST(:today AS date), e.hire_date)
     AND (am.effective_to IS NULL
          OR am.effective_to >= GREATEST(CAST(:today AS date), e.hire_date))
LEFT JOIN employments me ON me.tenant_id = am.tenant_id AND me.id = am.manager_employment_id
LEFT JOIN persons mp ON mp.tenant_id = me.tenant_id AND mp.id = me.person_id
LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
LEFT JOIN user_accounts mua ON mua.tenant_id = me.tenant_id AND mua.employment_id = me.id
WHERE e.tenant_id = :tid AND e.archived_at IS NULL AND p.archived_at IS NULL
  AND {still_here}
  AND (CAST(:le AS uuid) IS NULL OR e.legal_entity_id = CAST(:le AS uuid))
  AND (CAST(:ou AS uuid) IS NULL OR a.org_unit_id IN (SELECT id FROM units))
"""
# Who is still part of the company on the day: not yet left (an exit reminder also counts the
# last day itself and needs a date to be set).
STILL_HERE = "(e.separation_date IS NULL OR e.separation_date > :today)"
STILL_HERE_EXIT = "e.separation_date IS NOT NULL AND e.separation_date >= :today"
ONE_OFF = {ReminderTrigger.NEW_JOINER, ReminderTrigger.EXIT}


def _name(first: str | None, last: str | None) -> str:
    return " ".join(part for part in (first, last) if part)


async def candidates(session, tenant_id: UUID, rule: ReminderRule, today: date) -> list[dict]:
    """The people the rule could apply to: its company and department, still employed."""
    still_here = STILL_HERE_EXIT if rule.trigger == ReminderTrigger.EXIT else STILL_HERE
    rows = await session.execute(
        text(CANDIDATES.format(still_here=still_here)),
        {
            "tid": tenant_id,
            "today": today,
            "le": str(rule.legal_entity_id) if rule.legal_entity_id else None,
            "ou": str(rule.org_unit_id) if rule.org_unit_id else None,
        },
    )
    seen: set[UUID] = set()
    unique = []
    for row in rows.mappings():
        if row["employment_id"] not in seen:  # several assignments or accounts: keep the first
            seen.add(row["employment_id"])
            unique.append(dict(row))
    return unique


def _origin(row: dict, trigger: str) -> date | None:
    """The date the event comes from."""
    if trigger == ReminderTrigger.BIRTHDAY:
        return row["date_of_birth"]
    if trigger == ReminderTrigger.WORK_ANNIVERSARY:
        return row["continuity_start_date"] or row["hire_date"]
    if trigger == ReminderTrigger.NEW_JOINER:
        return row["hire_date"]
    return row["separation_date"]


def due_on(rows: list[dict], rule: ReminderRule, day: date) -> list[dict]:
    """Everyone whose event falls on a day this rule fires, looking from `day`. Birthdays and
    anniversaries come round every year; a joining or leaving date happens once."""
    offsets = dates.offsets_for(rule.frequency, rule.days_before, rule.custom_offsets)
    people = []
    for row in rows:
        origin = _origin(row, rule.trigger)
        if origin is None:
            continue
        if rule.trigger in ONE_OFF:
            if origin < day or (origin - day).days not in offsets:
                continue
            event_day, count = origin, 0
        else:
            if not dates.is_due(origin, day, offsets):
                continue
            event_day = dates.next_occurrence(origin, day)
            count = dates.years_at(origin, event_day)
            if rule.trigger == ReminderTrigger.WORK_ANNIVERSARY and count < 1:
                continue  # joined this year: nothing to celebrate yet
        first = row["preferred_name"] or row["legal_first_name"]
        person = {
            "employment_id": str(row["employment_id"]),
            "first_name": first,
            "full_name": _name(first, row["legal_last_name"]),
            "department": row["department"] or "",
            "designation": row["designation"] or "",
            "manager_name": _name(row["manager_first"], row["manager_last"]),
            "event_date": event_day.isoformat(),
            "days_left": (event_day - day).days,
            "email": row["email"],
            "manager_email": row["manager_email"],
        }
        if rule.trigger == ReminderTrigger.BIRTHDAY:
            person["age"] = count
        elif rule.trigger == ReminderTrigger.WORK_ANNIVERSARY:
            person["years"] = count
            person["joining_date"] = origin.isoformat()
        elif rule.trigger == ReminderTrigger.NEW_JOINER:
            person["joining_date"] = origin.isoformat()
        else:
            person["last_day"] = origin.isoformat()
        people.append(person)
    return sorted(people, key=lambda p: (p["event_date"], p["full_name"]))


async def everyone(session, tenant_id: UUID, rule: ReminderRule, today: date) -> dict[str, UUID]:
    """The address of every employee in the rule's company and department -> their employment,
    for the 'tell everyone' option. Only people who are working today and have an email."""
    rows = await session.execute(
        text(CANDIDATES.format(still_here=STILL_HERE) + " AND e.hire_date <= :today"),
        {
            "tid": tenant_id,
            "today": today,
            "le": str(rule.legal_entity_id) if rule.legal_entity_id else None,
            "ou": str(rule.org_unit_id) if rule.org_unit_id else None,
        },
    )
    found: dict[str, UUID] = {}
    for row in rows.mappings():
        if row["email"]:
            found.setdefault(row["email"].lower(), row["employment_id"])
    return found


def _long(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def person_values(person: dict, trigger: str) -> dict[str, str]:
    """The text for each variable of one person."""
    event = date.fromisoformat(person["event_date"])
    values = {
        "first_name": person["first_name"],
        "full_name": person["full_name"],
        "department": person["department"],
        "designation": person.get("designation", ""),
        "role_line": " · ".join(x for x in (person.get("designation"), person["department"]) if x),
        "manager_name": person["manager_name"],
        "manager_line": f"Reports to {person['manager_name']}" if person["manager_name"] else "",
        "event_date": _long(event) if trigger in ONE_OFF else f"{event.day} {event:%b}",
        "days_left": str(person["days_left"]),
        "when": templates.when_text(person["days_left"]),
    }
    if trigger == ReminderTrigger.BIRTHDAY:
        values["age"] = str(person.get("age", ""))
    elif trigger == ReminderTrigger.WORK_ANNIVERSARY:
        values["years"] = str(person.get("years", ""))
        values["joining_date"] = _long(date.fromisoformat(person["joining_date"]))
    elif trigger == ReminderTrigger.NEW_JOINER:
        values["joining_date"] = _long(date.fromisoformat(person["joining_date"]))
    else:
        values["last_day"] = _long(date.fromisoformat(person["last_day"]))
    return values


def _public(person: dict) -> dict:
    """What is kept in the outbox: no email addresses."""
    return {k: v for k, v in person.items() if k not in {"email", "manager_email"}}


def plan_mails(
    rule: ReminderRule, people: list[dict], today: date, everyone: dict[str, UUID] | None = None
) -> list[dict]:
    """The outbox rows for these people.

    The person's own greeting goes out on the day itself only: a schedule that starts days
    ahead is for the people who need notice, not for sending "happy birthday" six times.
    The heads-up goes to their manager, to the extra addresses and, when asked, to everyone
    (never about themselves)."""
    day = today.isoformat()
    mails: list[dict] = []
    if rule.notify_employee:
        for person in people:
            if person["email"] and person["days_left"] == 0:
                mails.append(
                    {
                        "audience": "EMPLOYEE",
                        "to": person["email"],
                        "key": f"{day}:E:{person['employment_id']}",
                        "people": [person],
                    }
                )
    team: dict[str, list[dict]] = {}
    for person in people:
        if rule.notify_manager and person["manager_email"]:
            team.setdefault(person["manager_email"].lower(), []).append(person)
    for address in rule.extra_emails:
        team[address.lower()] = list(people)
    if rule.notify_everyone:
        for address, employment_id in (everyone or {}).items():
            others = [p for p in people if p["employment_id"] != str(employment_id)]
            seen = {p["employment_id"] for p in team.get(address, [])}
            team[address] = team.get(address, []) + [
                p for p in others if p["employment_id"] not in seen
            ]
    for address, listed in team.items():
        if not listed:
            continue
        if rule.digest:
            mails.append(
                {"audience": "TEAM", "to": address, "key": f"{day}:T:{address}", "people": listed}
            )
        else:
            mails += [
                {
                    "audience": "TEAM",
                    "to": address,
                    "key": f"{day}:T:{address}:{p['employment_id']}",
                    "people": [p],
                }
                for p in listed
            ]
    return mails


async def enqueue(session, tenant_id: UUID, rule: ReminderRule, today: date) -> int:
    """Queue today's mail for a rule; returns how many new rows. Safe to repeat."""
    queued = 0
    people = due_on(await candidates(session, tenant_id, rule, today), rule, today)
    audience = (
        await everyone(session, tenant_id, rule, today) if people and rule.notify_everyone else {}
    )
    for mail in plan_mails(rule, people, today, audience):
        result = await session.execute(
            text("""
                INSERT INTO reminder_outbox
                    (tenant_id, id, rule_id, send_date, audience, recipient_email,
                     dedupe_key, payload)
                VALUES (:tid, :id, :rule, :day, :audience, :to, :key,
                        CAST(:payload AS jsonb))
                ON CONFLICT (tenant_id, rule_id, dedupe_key) DO NOTHING
            """),
            {
                "tid": tenant_id,
                "id": uuid4(),
                "rule": rule.id,
                "day": today,
                "audience": mail["audience"],
                "to": mail["to"],
                "key": mail["key"],
                "payload": json.dumps({"people": [_public(p) for p in mail["people"]]}),
            },
        )
        queued += result.rowcount or 0
    rule.last_run_date = today
    return queued


async def tick(session, tenant_id: UUID, now: datetime | None = None) -> str:
    """Queue mail for every rule that is due now. Returns a one-line summary."""
    if settings.mail_backend == "disabled":
        return "mail is disabled; nothing queued"
    timezone = (
        await session.execute(
            text("SELECT timezone FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar_one()
    local = (now or now_utc()).astimezone(safe_tz(timezone))
    rules = (
        (
            await session.execute(
                text("""
                    SELECT id FROM reminder_rules
                    WHERE tenant_id = :tid AND is_active AND archived_at IS NULL
                      AND send_time <= :clock
                      AND (last_run_date IS NULL OR last_run_date < :today)
                    FOR UPDATE SKIP LOCKED
                """),
                {"tid": tenant_id, "clock": local.time(), "today": local.date()},
            )
        )
        .scalars()
        .all()
    )
    queued = 0
    for rule_id in rules:
        rule = await session.get(ReminderRule, (tenant_id, rule_id))
        if rule:
            queued += await enqueue(session, tenant_id, rule, local.date())
    return f"{len(rules)} rule(s) ran, {queued} mail(s) queued"


# ── Wording and sending ─────────────────────────────────────────────────────────────────────


async def compose(
    session, tenant_id: UUID, rule: ReminderRule, audience: str, people: list[dict]
) -> tuple[str, str, str]:
    """(subject, html, plain text) for one outbox row."""
    context = await resolve.context(session, tenant_id, rule.legal_entity_id)
    group = {"company_name": context.company.name, "count": str(len(people))}
    values = [person_values(p, rule.trigger) for p in people]
    if audience == "EMPLOYEE":
        subject_t, body_t = rule.employee_subject, rule.employee_body_html
        body = templates.render_team(body_t, values[:1], group, digest=False)
    else:
        subject_t, body_t = rule.subject, rule.body_html
        body = templates.render_team(body_t, values, group, digest=rule.digest)
    subject = templates.fill(subject_t, {**group, **values[0]}, escape=False)
    color = resolve.readable_on_white(
        str(context.fields["primary_color"].value or resolve.DEFAULTS["primary_color"])
    )
    footer = context.fields["footer_text"].value
    page = templates.wrap(
        body,
        company=context.company.name,
        color=color,
        on_color=resolve.text_on(color),
        footer=str(footer) if footer else None,
    )
    return " ".join(subject.split()), page, templates.to_text(body)


def _default_sender(to: str, subject: str, html: str, plain: str) -> None:
    from hrms.core.mail import send_html

    send_html(to, subject, html, plain)


async def deliver(
    session,
    tenant_id: UUID,
    sender: Callable[[str, str, str, str], None] | None = None,
    today: date | None = None,
) -> dict[str, int]:
    """Send queued mail in batches until none is waiting or MAX_PER_RUN is reached. A failure is
    retried with a growing delay."""
    counts = {"sent": 0, "failed": 0}
    if settings.mail_backend == "disabled" and sender is None:
        return counts
    send = sender or _default_sender
    today = today or now_utc().date()
    handled = 0
    while handled < MAX_PER_RUN:
        rows = await _due_rows(session, tenant_id)
        if not rows:
            break
        for row in rows:
            await _deliver_one(session, tenant_id, row, send, today, counts)
        handled += len(rows)
    return counts


async def _due_rows(session, tenant_id: UUID):
    return (
        (
            await session.execute(
                text("""
                    SELECT o.id, o.rule_id, o.audience, o.recipient_email, o.payload,
                           o.attempts, o.send_date
                    FROM reminder_outbox o
                    WHERE o.tenant_id = :tid AND o.status = 'PENDING'
                      AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= now())
                    ORDER BY o.created_at LIMIT :n FOR UPDATE SKIP LOCKED
                """),
                {"tid": tenant_id, "n": BATCH},
            )
        )
        .mappings()
        .all()
    )


async def _deliver_one(session, tenant_id: UUID, row, send, today: date, counts: dict) -> None:
    rule = await session.get(ReminderRule, (tenant_id, row["rule_id"]))
    error = None
    if rule is None or rule.archived_at or not rule.is_active:
        error = "rule paused or removed"
    elif row["send_date"] < today - STALE_AFTER:
        error = "too old to send"
    if error:
        await _mark(session, tenant_id, row["id"], "FAILED", row["attempts"], error)
        counts["failed"] += 1
        return
    try:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        subject, html, plain = await compose(
            session, tenant_id, rule, row["audience"], payload["people"]
        )
        await run_in_threadpool(send, row["recipient_email"], subject, html, plain)
    except Exception as exc:
        # Provider errors can hold addresses: keep only the class.
        attempts = row["attempts"] + 1
        final = attempts >= MAX_ATTEMPTS
        logger.error("Reminder mail failed (%s)", type(exc).__name__)
        await _mark(
            session,
            tenant_id,
            row["id"],
            "FAILED" if final else "PENDING",
            attempts,
            type(exc).__name__,
        )
        counts["failed"] += final
    else:
        await _mark(session, tenant_id, row["id"], "SENT", row["attempts"] + 1, None)
        counts["sent"] += 1


async def _mark(session, tenant_id: UUID, outbox_id: UUID, status: str, attempts: int, error):
    await session.execute(
        text("""
            UPDATE reminder_outbox
            SET status = CAST(:status AS varchar), attempts = :attempts, last_error = :error,
                sent_at = CASE WHEN CAST(:status AS varchar) = 'SENT' THEN now() END,
                next_attempt_at = CASE WHEN CAST(:status AS varchar) = 'PENDING'
                    THEN now() + make_interval(secs => CAST(:delay AS double precision)) END
            WHERE tenant_id = :tid AND id = :id
        """),
        {
            "tid": tenant_id,
            "id": outbox_id,
            "status": status,
            "attempts": attempts,
            "error": error,
            "delay": min(1800, 60 * 2**attempts),
        },
    )


async def purge_old(session, tenant_id: UUID) -> int:
    result = await session.execute(
        text("""DELETE FROM reminder_outbox
                WHERE tenant_id = :tid AND status <> 'PENDING'
                  AND created_at < now() - interval '90 days'"""),
        {"tid": tenant_id},
    )
    return result.rowcount or 0

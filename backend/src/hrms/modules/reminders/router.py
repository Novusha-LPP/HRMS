"""
Date reminders — /v1/reminders. Birthday and work-anniversary mail on a schedule HR defines.

Rules        GET/POST /rules   GET/PATCH/DELETE /rules/{id}   GET /rules/{id}/history
Checking     POST /preview (a draft, filled with sample people)   GET /rules/{id}/upcoming
             POST /rules/{id}/test-send (to yourself)
Reference    GET /variables   GET /defaults   GET /deliveries

Access: org.read to see, org.write to change (HR and Admin). A rule for the whole group needs
group-level org.write; a rule for one company needs org.write covering that company.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlmodel import col, select
from starlette.concurrency import run_in_threadpool

from hrms.core.authn import CurrentUser
from hrms.core.authz import Scope, ScopeDep, require_permission
from hrms.core.change_audit import record_change
from hrms.core.config import settings
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc, safe_tz
from hrms.core.errors import CodedHTTPException
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.core.versioning import require_version
from hrms.modules.kernel.models import EntityChangeLog
from hrms.modules.org.models import LegalEntity, OrgUnit
from hrms.modules.reminders import dates, service, templates
from hrms.modules.reminders.models import ReminderRule, ReminderTrigger
from hrms.modules.reminders.schemas import (
    ChangeResponse,
    DeliveryResponse,
    DraftPreview,
    PreviewResponse,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
    UpcomingPerson,
)

router = APIRouter(prefix="/v1/reminders", tags=["Reminders"])

SAMPLE_PEOPLE = [
    {
        "employment_id": "sample-1",
        "first_name": "Asha",
        "full_name": "Asha Patel",
        "department": "Sales",
        "designation": "Executive",
        "last_day": "2000-01-01",
        "manager_name": "Ravi Shah",
        "event_date": "2000-01-01",
        "days_left": 0,
        "age": 32,
        "years": 5,
        "joining_date": "2020-01-01",
    },
    {
        "employment_id": "sample-2",
        "first_name": "Imran",
        "full_name": "Imran Khan",
        "department": "Finance",
        "designation": "Accountant",
        "last_day": "2000-01-04",
        "manager_name": "Meera Iyer",
        "event_date": "2000-01-04",
        "days_left": 3,
        "age": 41,
        "years": 10,
        "joining_date": "2015-01-04",
    },
]
RULE_FIELDS = tuple(f for f in RuleUpdate.model_fields if f != "version")


def _response(rule: ReminderRule) -> RuleResponse:
    return RuleResponse(
        id=to_typed_id("reminder_rule", rule.id),
        name=rule.name,
        trigger=rule.trigger,
        legal_entity_id=(
            to_typed_id("legal_entity", rule.legal_entity_id) if rule.legal_entity_id else None
        ),
        org_unit_id=to_typed_id("org_unit", rule.org_unit_id) if rule.org_unit_id else None,
        frequency=rule.frequency,
        days_before=rule.days_before,
        custom_offsets=list(rule.custom_offsets),
        send_time=rule.send_time,
        notify_employee=rule.notify_employee,
        notify_manager=rule.notify_manager,
        notify_everyone=rule.notify_everyone,
        extra_emails=list(rule.extra_emails),
        digest=rule.digest,
        subject=rule.subject,
        body_html=rule.body_html,
        employee_subject=rule.employee_subject,
        employee_body_html=rule.employee_body_html,
        is_active=rule.is_active,
        version=rule.version,
        last_run_date=rule.last_run_date,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _check_scope(scope: Scope, legal_entity_id: UUID | None) -> None:
    if legal_entity_id is None:
        if not scope.is_all:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only a group-level administrator can set a group-wide rule",
            )
    elif not scope.covers_entity(legal_entity_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")


async def _load(session, tenant_id: UUID, typed_id: str) -> ReminderRule:
    rule = await session.get(ReminderRule, (tenant_id, to_uuid(typed_id)))
    if rule is None or rule.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reminder rule not found")
    return rule


async def _visible(session, tenant_id: UUID, typed_id: str, scope: Scope) -> ReminderRule:
    """The rule, if the caller's org.read scope covers its company."""
    rule = await _load(session, tenant_id, typed_id)
    read = scope.for_permission("org.read")
    if not read.is_all and not (rule.legal_entity_id and read.covers_entity(rule.legal_entity_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reminder rule not found")
    return rule


async def _refs(session, tenant_id: UUID, entity_id: str | None, unit_id: str | None):
    """The company and department a rule is limited to, checked to exist in this tenant."""
    le = to_uuid(entity_id) if entity_id else None
    ou = to_uuid(unit_id) if unit_id else None
    if le and await session.get(LegalEntity, (tenant_id, le)) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown company")
    if ou:
        unit = await session.get(OrgUnit, (tenant_id, ou))
        if unit is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown department")
        if le and unit.legal_entity_id and unit.legal_entity_id != le:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That department belongs to another company"
            )
    return le, ou


def _check_consistent(rule: ReminderRule) -> None:
    """The cross-field rules RuleCreate enforces, applied to a rule after a partial edit."""
    problems = []
    if not (
        rule.notify_employee or rule.notify_manager or rule.notify_everyone or rule.extra_emails
    ):
        problems.append("Choose at least one person to tell.")
    if rule.frequency == "CUSTOM" and not rule.custom_offsets:
        problems.append("Enter at least one day for a custom schedule.")
    if rule.frequency in {"CONTINUOUS", "ALTERNATE_DAYS"} and rule.days_before < 1:
        problems.append("Say how many days before it starts.")
    if any(not 0 <= d <= dates.MAX_OFFSET for d in rule.custom_offsets):
        problems.append(f"Each day must be between 0 and {dates.MAX_OFFSET}.")
    if problems:
        raise CodedHTTPException(422, " ".join(problems), code="REMINDER_RULE_INVALID")


def _check_wording(rule: ReminderRule) -> None:
    """Refuse a subject or body with a variable that does not exist, so no mail ever goes out
    with a literal {placeholder} in it."""
    problems: list[str] = []
    for label, value, own in (
        ("Subject", rule.subject, False),
        ("Message", rule.body_html, False),
        ("Employee subject", rule.employee_subject, True),
        ("Employee message", rule.employee_body_html, True),
    ):
        problems += [
            f"{label}: {p}"
            for p in templates.validate(
                value, rule.trigger, per_person_only=own, digest=rule.digest and not own
            )
        ]
    if problems:
        raise CodedHTTPException(422, " ".join(problems), code="REMINDER_WORDING_INVALID")


async def _local_now(session, tenant_id: UUID):
    zone = (
        await session.execute(
            text("SELECT timezone FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar_one()
    return now_utc().astimezone(safe_tz(zone))


async def _skip_today_if_past(session, tenant_id: UUID, rule: ReminderRule) -> None:
    """A rule saved after its time of day has passed starts tomorrow, not at once."""
    local = await _local_now(session, tenant_id)
    if rule.is_active and rule.send_time <= local.time():
        rule.last_run_date = local.date()


def _snapshot(rule: ReminderRule, fields) -> dict:
    return {f: getattr(rule, f) for f in fields if f != "version"}


# ─── Reference ───────────────────────────────────────────────────────────────


@router.get("/variables", dependencies=[require_permission("org.read")])
async def reminder_variables(trigger: ReminderTrigger) -> dict:
    """The {variables} the wording may use, with what each one fills in."""
    return {"variables": templates.variables_for(trigger)}


@router.get("/defaults", dependencies=[require_permission("org.read")])
async def reminder_defaults(trigger: ReminderTrigger) -> dict[str, str]:
    """Starter wording for a new rule."""
    return templates.DEFAULTS[trigger]


# ─── Rules ───────────────────────────────────────────────────────────────────


@router.get(
    "/rules", response_model=list[RuleResponse], dependencies=[require_permission("org.read")]
)
async def list_reminder_rules(tenant_id: TenantDep, session: SessionDep, scope: ScopeDep):
    read = scope.for_permission("org.read")
    rows = await session.execute(
        select(ReminderRule)
        .where(ReminderRule.tenant_id == tenant_id)
        .where(col(ReminderRule.archived_at).is_(None))
        .order_by(col(ReminderRule.created_at))
    )
    return [
        _response(r)
        for r in rows.scalars()
        if read.is_all or (r.legal_entity_id and read.covers_entity(r.legal_entity_id))
    ]


@router.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_permission("org.write")],
)
async def create_reminder_rule(
    body: RuleCreate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
):
    le, ou = await _refs(session, tenant_id, body.legal_entity_id, body.org_unit_id)
    _check_scope(scope.for_permission("org.write"), le)
    fields = body.model_dump(exclude={"legal_entity_id", "org_unit_id"})
    rule = ReminderRule(
        tenant_id=tenant_id,
        id=uuid4(),
        legal_entity_id=le,
        org_unit_id=ou,
        created_by=principal.user_account_id,
        updated_by=principal.user_account_id,
        **fields,
    )
    rule.subject = rule.subject.strip()
    rule.body_html = templates.sanitize_html(rule.body_html)
    rule.employee_body_html = templates.sanitize_html(rule.employee_body_html)
    _check_wording(rule)
    await _skip_today_if_past(session, tenant_id, rule)
    session.add(rule)
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "reminder_rule",
        rule.id,
        "CREATE",
        principal.user_account_id,
        None,
        _snapshot(rule, RULE_FIELDS),
    )
    return _response(rule)


@router.get(
    "/rules/{rule_id}", response_model=RuleResponse, dependencies=[require_permission("org.read")]
)
async def get_reminder_rule(
    rule_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
):
    return _response(await _visible(session, tenant_id, rule_id, scope))


@router.patch(
    "/rules/{rule_id}", response_model=RuleResponse, dependencies=[require_permission("org.write")]
)
async def update_reminder_rule(
    rule_id: str,
    body: RuleUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
):
    rule = await _load(session, tenant_id, rule_id)
    write = scope.for_permission("org.write")
    _check_scope(write, rule.legal_entity_id)
    sent = body.model_dump(
        exclude_unset=True, exclude={"version", "legal_entity_id", "org_unit_id"}
    )
    scope_change = {"legal_entity_id", "org_unit_id"} & body.model_fields_set
    names = [*sent, *scope_change]
    before = _snapshot(rule, names)
    was_active, old_time = rule.is_active, rule.send_time
    await require_version(session, rule, body.version)
    if scope_change:
        le, ou = await _refs(
            session,
            tenant_id,
            body.legal_entity_id
            if "legal_entity_id" in scope_change
            else (
                to_typed_id("legal_entity", rule.legal_entity_id) if rule.legal_entity_id else None
            ),
            body.org_unit_id
            if "org_unit_id" in scope_change
            else (to_typed_id("org_unit", rule.org_unit_id) if rule.org_unit_id else None),
        )
        _check_scope(write, le)
        rule.legal_entity_id, rule.org_unit_id = le, ou
    for name, value in sent.items():
        setattr(rule, name, value)
    if "body_html" in sent:
        rule.body_html = templates.sanitize_html(rule.body_html)
    if "employee_body_html" in sent:
        rule.employee_body_html = templates.sanitize_html(rule.employee_body_html)
    if "extra_emails" in sent:
        rule.extra_emails = list(dict.fromkeys(e.strip().lower() for e in rule.extra_emails))
    if "custom_offsets" in sent:
        rule.custom_offsets = sorted(set(rule.custom_offsets))
    _check_consistent(rule)
    _check_wording(rule)
    if (rule.is_active and not was_active) or rule.send_time != old_time:
        await _skip_today_if_past(session, tenant_id, rule)
    rule.updated_by = principal.user_account_id
    rule.updated_at = now_utc()
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "reminder_rule",
        rule.id,
        "UPDATE",
        principal.user_account_id,
        before,
        _snapshot(rule, names),
    )
    return _response(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_permission("org.write")],
)
async def delete_reminder_rule(
    rule_id: str,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
):
    rule = await _load(session, tenant_id, rule_id)
    _check_scope(scope.for_permission("org.write"), rule.legal_entity_id)
    before = _snapshot(rule, ["is_active", "archived_at"])
    rule.is_active, rule.archived_at = False, now_utc()
    rule.updated_by, rule.updated_at = principal.user_account_id, now_utc()
    rule.version += 1
    await session.flush()
    await record_change(
        session,
        tenant_id,
        "reminder_rule",
        rule.id,
        "ARCHIVE",
        principal.user_account_id,
        before,
        None,
    )


@router.get(
    "/rules/{rule_id}/history",
    response_model=list[ChangeResponse],
    dependencies=[require_permission("org.read")],
)
async def reminder_rule_history(
    rule_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
):
    rule = await _visible(session, tenant_id, rule_id, scope)
    rows = await session.execute(
        select(EntityChangeLog)
        .where(EntityChangeLog.tenant_id == tenant_id)
        .where(EntityChangeLog.entity_type == "reminder_rule")
        .where(EntityChangeLog.entity_id == rule.id)
        .order_by(col(EntityChangeLog.changed_at).desc())
        .limit(100)
    )
    return [
        ChangeResponse(
            action=r.action,
            changed_by=to_typed_id("user_account", r.changed_by),
            changed_at=r.changed_at,
            changes=r.changes,
        )
        for r in rows.scalars()
    ]


# ─── Checking a rule before it matters ───────────────────────────────────────


def _draft_rule(body: DraftPreview, tenant_id: UUID, legal_entity_id: UUID | None) -> ReminderRule:
    """An unsaved rule carrying just the draft wording, so previews use the real renderer."""
    return ReminderRule(
        tenant_id=tenant_id,
        id=uuid4(),
        name="preview",
        trigger=body.trigger,
        legal_entity_id=legal_entity_id,
        frequency="SAME_DAY",
        send_time=time(9),
        digest=body.digest,
        subject=body.subject,
        body_html=body.body_html,
        employee_subject=body.subject,
        employee_body_html=body.body_html,
    )


@router.post(
    "/preview", response_model=PreviewResponse, dependencies=[require_permission("org.read")]
)
async def preview_reminder_wording(body: DraftPreview, tenant_id: TenantDep, session: SessionDep):
    """A draft wording filled in with two sample people, exactly as it would be mailed."""
    own = body.audience == "EMPLOYEE"
    problems = [
        *templates.validate(
            body.subject, body.trigger, per_person_only=own, digest=body.digest and not own
        ),
        *templates.validate(
            body.body_html, body.trigger, per_person_only=own, digest=body.digest and not own
        ),
    ]
    le = to_uuid(body.legal_entity_id) if body.legal_entity_id else None
    rule = _draft_rule(body, tenant_id, le)
    subject, html, plain = await service.compose(
        session, tenant_id, rule, body.audience, SAMPLE_PEOPLE[: 1 if own else 2]
    )
    return PreviewResponse(subject=subject, html=html, text=plain, problems=problems)


@router.post("/rules/{rule_id}/test-send", dependencies=[require_permission("org.write")])
async def test_send_reminder(
    rule_id: str,
    audience: str,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> dict[str, str]:
    """Mail the rule's wording, filled with sample people, to your own address."""
    if audience not in {"EMPLOYEE", "TEAM"}:
        raise HTTPException(422, "audience must be EMPLOYEE or TEAM")
    if settings.mail_backend == "disabled":
        raise CodedHTTPException(
            409, "Mail is not switched on for this system", code="MAIL_DISABLED"
        )
    rule = await _load(session, tenant_id, rule_id)
    _check_scope(scope.for_permission("org.write"), rule.legal_entity_id)
    address = (
        await session.execute(
            text("SELECT email FROM user_accounts WHERE tenant_id = :tid AND id = :uid"),
            {"tid": tenant_id, "uid": principal.user_account_id},
        )
    ).scalar()
    if not address:
        raise CodedHTTPException(409, "Your account has no email address", code="NO_EMAIL")
    subject, html, plain = await service.compose(
        session, tenant_id, rule, audience, SAMPLE_PEOPLE[: 1 if audience == "EMPLOYEE" else 2]
    )
    await run_in_threadpool(service._default_sender, address, "[Test] " + subject, html, plain)
    return {"sent_to": address}


@router.get(
    "/rules/{rule_id}/upcoming",
    response_model=list[UpcomingPerson],
    dependencies=[require_permission("org.read")],
)
async def upcoming_reminders(
    rule_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    days: int = Query(default=30, ge=1, le=90),
):
    """Who the rule will mail about over the next days, and on which dates."""
    rule = await _visible(session, tenant_id, rule_id, scope)
    today = (await _local_now(session, tenant_id)).date()
    rows = await service.candidates(session, tenant_id, rule, today)
    found: dict[str, UpcomingPerson] = {}
    for offset in range(days):
        day = today + timedelta(days=offset)
        for person in service.due_on(rows, rule, day):
            entry = found.setdefault(
                person["employment_id"],
                UpcomingPerson(
                    full_name=person["full_name"],
                    department=person["department"],
                    event_date=date.fromisoformat(person["event_date"]),
                    days_left=(date.fromisoformat(person["event_date"]) - today).days,
                    sends_on=[],
                ),
            )
            entry.sends_on.append(day)
    return sorted(found.values(), key=lambda p: (p.event_date, p.full_name))


@router.get(
    "/deliveries",
    response_model=list[DeliveryResponse],
    dependencies=[require_permission("org.write")],
)
async def reminder_deliveries(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    rule_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Recent mail: queued, sent, or failed. Recipient addresses are visible to org.write only."""
    rows = await session.execute(
        text("""
            SELECT o.id, o.rule_id, o.send_date, o.audience, o.recipient_email, o.status,
                   o.attempts, o.sent_at, o.last_error, r.legal_entity_id
            FROM reminder_outbox o
            JOIN reminder_rules r ON r.tenant_id = o.tenant_id AND r.id = o.rule_id
            WHERE o.tenant_id = :tid
              AND (CAST(:rule AS uuid) IS NULL OR o.rule_id = CAST(:rule AS uuid))
            ORDER BY o.created_at DESC LIMIT :n
        """),
        {"tid": tenant_id, "rule": str(to_uuid(rule_id)) if rule_id else None, "n": limit},
    )
    write = scope.for_permission("org.write")
    return [
        DeliveryResponse(
            id=to_typed_id("reminder_mail", r["id"]),
            rule_id=to_typed_id("reminder_rule", r["rule_id"]),
            send_date=r["send_date"],
            audience=r["audience"],
            recipient_email=r["recipient_email"],
            status=r["status"],
            attempts=r["attempts"],
            sent_at=r["sent_at"],
            last_error=r["last_error"],
        )
        for r in rows.mappings()
        if write.is_all or (r["legal_entity_id"] and write.covers_entity(r["legal_entity_id"]))
    ]

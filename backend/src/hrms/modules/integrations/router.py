"""
/v1/integrations/* — the API a connected app (ERP, CRM, BI tool) calls with its own credential.

Authentication is an API key (X-API-Key) or a 15-minute token from /oauth/token; see keys.py.
Every write is logged in the sync log (integration_requests), including refusals, which are
written in their own transaction so they survive the request's rollback.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Form, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import text

from hrms.core import database
from hrms.core.datetime_utils import business_today
from hrms.core.errors import CodedHTTPException
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.metrics import INTEGRATION_REQUESTS, INTEGRATION_SESSIONS
from hrms.core.security import create_access_token
from hrms.modules.integrations import events, service
from hrms.modules.integrations.keys import IntegrationContext, IntegrationDep, issue_client_token
from hrms.modules.integrations.profiles import effective_settings
from hrms.modules.integrations.schemas import (
    BulkItem,
    BulkRequest,
    BulkResponse,
    EmployeeUpsert,
    ExitRequest,
    FeedResponse,
    LinkRequest,
    ReconcileRequest,
    RehireRequest,
    SessionRequest,
    SessionResponse,
    SyncResult,
    TokenResponse,
)

router = APIRouter(prefix="/v1/integrations", tags=["Integrations"])


# ─── The sync log ────────────────────────────────────────────────────────────


async def _insert_log(session, ctx: IntegrationContext, **row: Any) -> None:
    await session.execute(
        text("""
        INSERT INTO integration_requests
            (tenant_id, id, app_id, api_key_id, operation, external_id, employment_id,
             idempotency_key, request_hash, outcome, error_code, error_detail, changes, warnings,
             response, http_status, duration_ms, request_id)
        VALUES (:tid, :id, :app, :key, :operation, :external_id, :employment_id,
                :idempotency_key, :request_hash, :outcome, :error_code,
                CAST(:error_detail AS jsonb), CAST(:changes AS jsonb), CAST(:warnings AS jsonb),
                CAST(:response AS jsonb), :http_status, :duration_ms, :request_id)
    """),
        {
            "tid": ctx.tenant_id,
            "id": uuid4(),
            "app": ctx.app_id,
            "key": ctx.key_id,
            "operation": row["operation"],
            "external_id": row.get("external_id"),
            "employment_id": row.get("employment_id"),
            "idempotency_key": row.get("idempotency_key"),
            "request_hash": row.get("request_hash"),
            "outcome": row["outcome"],
            "error_code": row.get("error_code"),
            "error_detail": _dump(row.get("error_detail")),
            "changes": _dump(_mask(row.get("changes"))),
            "warnings": _dump(row.get("warnings") or None),
            "response": _dump(row.get("response")),
            "http_status": row.get("http_status"),
            "duration_ms": row.get("duration_ms"),
            "request_id": ctx.request_id,
        },
    )
    INTEGRATION_REQUESTS.labels(ctx.app_code, row["operation"], row["outcome"]).inc()


def _dump(value: Any) -> str | None:
    return json.dumps(jsonable_encoder(value)) if value is not None else None


def _mask(changes: dict | None) -> dict | None:
    """Contact details are masked in the log; the log shows that they changed, not to what."""
    if not changes:
        return changes
    out = {}
    for key, value in changes.items():
        if key in ("email", "mobile") and isinstance(value, dict):
            out[key] = {k: _mask_value(v) for k, v in value.items()}
        elif key == "password":
            out[key] = {"old": "…", "new": "changed"}
        else:
            out[key] = value
    return out


def _mask_value(value: Any) -> Any:
    if not isinstance(value, str) or len(value) < 4:
        return value
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{name[:1]}…@{domain}"
    return f"…{value[-4:]}"


def _employment_uuid(result: SyncResult | None) -> UUID | None:
    return to_uuid(result.employment_id) if result and result.employment_id else None


async def _log_failure(
    ctx: IntegrationContext,
    operation: str,
    external_id: str | None,
    exc: Exception,
    started: float,
    idempotency_key: str | None = None,
) -> None:
    status = exc.status_code if isinstance(exc, HTTPException) else 500
    code = getattr(exc, "code", None) or ("INTERNAL_ERROR" if status >= 500 else "REJECTED")
    detail = getattr(exc, "sync_detail", None) or {}
    async with database.AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(ctx.tenant_id)}
        )
        await _insert_log(
            session,
            ctx,
            operation=operation,
            external_id=external_id,
            idempotency_key=idempotency_key,
            outcome="FAILED" if status >= 500 else "REJECTED",
            error_code=code,
            error_detail={
                "message": exc.detail if isinstance(exc, HTTPException) else type(exc).__name__,
                **{k: v for k, v in detail.items() if k != "payload"},
            },
            http_status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        for dup in detail.get("duplicates", []):
            await session.execute(
                text("""
                INSERT INTO possible_duplicates
                    (tenant_id, id, app_id, external_id, employment_id, match_reason, payload)
                VALUES (:tid, :id, :app, :ext, :eid, :reason, CAST(:payload AS jsonb))
                ON CONFLICT (tenant_id, app_id, external_id, employment_id)
                    WHERE status = 'OPEN'
                DO UPDATE SET payload = EXCLUDED.payload, created_at = now()
            """),
                {
                    "tid": ctx.tenant_id,
                    "id": uuid4(),
                    "app": ctx.app_id,
                    "ext": external_id,
                    "eid": UUID(dup["employment_id"]),
                    "reason": dup["reason"],
                    "payload": json.dumps(detail.get("payload")),
                },
            )
        await session.commit()


async def _replay(ctx: IntegrationContext, idempotency_key: str | None, request_hash: str):
    """The stored response for a repeated Idempotency-Key, or None for a new one."""
    if not idempotency_key:
        return None
    await lock_resource(ctx.session, ctx.tenant_id, f"idem:{ctx.key_id}:{idempotency_key}")
    row = (
        (
            await ctx.session.execute(
                text("""
                SELECT request_hash, response, http_status FROM integration_requests
                WHERE tenant_id = :tid AND api_key_id = :key AND idempotency_key = :idem
                  AND outcome NOT IN ('REJECTED', 'FAILED')
            """),
                {"tid": ctx.tenant_id, "key": ctx.key_id, "idem": idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    if row["request_hash"] != request_hash:
        raise CodedHTTPException(
            422,
            "This Idempotency-Key was already used with a different request body",
            code="IDEMPOTENCY_KEY_REUSED",
        )
    return JSONResponse(
        row["response"],
        status_code=row["http_status"] or 200,
        headers={"Idempotent-Replay": "true"},
    )


async def _logged(
    ctx: IntegrationContext,
    operation: str,
    external_id: str | None,
    action: Callable[[], Awaitable[SyncResult]],
    *,
    idempotency_key: str | None = None,
    payload: Any = None,
    dry_run: bool = False,
    status_for: Callable[[SyncResult], int] = lambda r: 200,
):
    started = time.monotonic()
    request_hash = service.request_hash(payload)
    replay = await _replay(ctx, idempotency_key, request_hash)
    if replay is not None:
        return replay
    try:
        if dry_run:
            savepoint = await ctx.session.begin_nested()
            try:
                result = await action()
            finally:
                await savepoint.rollback()
            result.dry_run = True
        else:
            result = await action()
    except Exception as exc:
        await _log_failure(ctx, operation, external_id, exc, started, idempotency_key)
        raise
    result.request_id = ctx.request_id
    status = status_for(result)
    body = jsonable_encoder(result)
    await _insert_log(
        ctx.session,
        ctx,
        operation=operation,
        external_id=external_id,
        employment_id=None if dry_run else _employment_uuid(result),
        idempotency_key=None if dry_run else idempotency_key,
        request_hash=request_hash,
        outcome="DRY_RUN" if dry_run else result.outcome,
        changes=result.changes,
        warnings=result.warnings,
        response=body,
        http_status=status,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return JSONResponse(body, status_code=status)


# ─── OAuth ───────────────────────────────────────────────────────────────────


@router.post("/oauth/token", response_model=TokenResponse)
async def oauth_token(
    request: Request,
    grant_type: str = Form(...),
    client_id: str | None = Form(default=None),
    client_secret: str | None = Form(default=None),
) -> dict[str, Any]:
    if grant_type != "client_credentials":
        raise CodedHTTPException(
            400, "Only client_credentials is supported", code="unsupported_grant_type"
        )
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        import base64

        try:
            client_id, _, client_secret = base64.b64decode(auth[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError) as exc:
            raise CodedHTTPException(
                401, "Invalid client credentials", code="invalid_client"
            ) from exc
    if not client_id or not client_secret:
        raise CodedHTTPException(401, "Invalid client credentials", code="invalid_client")
    from hrms.core import throttle

    ip = throttle.client_ip(request)
    await throttle.ensure_not_locked("integration-token:ip", ip)
    try:
        return await issue_client_token(client_id, client_secret, ip)
    except HTTPException as exc:
        if exc.status_code == 401:
            await throttle.record_attempt(
                "integration-token:ip", ip, max_attempts=20, window_minutes=15, lock_minutes=15
            )
        raise


# ─── Reference data ──────────────────────────────────────────────────────────


@router.get("/reference-data")
async def reference_data(ctx: IntegrationDep) -> dict[str, Any]:
    ctx.require("employees.read")
    s, tid = ctx.session, ctx.tenant_id
    companies = (
        (
            await s.execute(
                text("""SELECT id, name, short_name FROM legal_entities
                    WHERE tenant_id = :tid AND archived_at IS NULL ORDER BY name"""),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    companies = [c for c in companies if ctx.covers_entity(c["id"])]
    allowed = {c["id"] for c in companies}
    departments = (
        (
            await s.execute(
                text("""SELECT id, name, code, type, legal_entity_id FROM org_units
                    WHERE tenant_id = :tid AND archived_at IS NULL
                      AND type <> 'DEPARTMENT_TEMPLATE' ORDER BY name"""),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    locations = (
        (
            await s.execute(
                text("""SELECT id, name, legal_entity_id FROM locations
                    WHERE tenant_id = :tid ORDER BY name"""),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    jobs = (
        (
            await s.execute(
                text("""SELECT id, title, code FROM jobs
                    WHERE tenant_id = :tid AND archived_at IS NULL ORDER BY title"""),
                {"tid": tid},
            )
        )
        .mappings()
        .all()
    )
    mappings = (
        (
            await s.execute(
                text("""SELECT kind, external_value, target_id, target_value
                        FROM integration_mappings
                    WHERE tenant_id = :tid AND app_id = :app ORDER BY kind, external_value"""),
                {"tid": tid, "app": ctx.app_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        "companies": [
            {"id": to_typed_id("legal_entity", c["id"]), "name": c["name"], "code": c["short_name"]}
            for c in companies
        ],
        "departments": [
            {
                "id": to_typed_id("org_unit", d["id"]),
                "name": d["name"],
                "code": d["code"],
                "type": d["type"],
                "company_id": to_typed_id("legal_entity", d["legal_entity_id"])
                if d["legal_entity_id"]
                else None,
            }
            for d in departments
            if d["legal_entity_id"] in allowed
        ],
        "locations": [
            {
                "id": to_typed_id("location", loc["id"]),
                "name": loc["name"],
                "company_id": to_typed_id("legal_entity", loc["legal_entity_id"])
                if loc["legal_entity_id"]
                else None,
            }
            for loc in locations
            if loc["legal_entity_id"] is None or loc["legal_entity_id"] in allowed
        ],
        "designations": [
            {"id": to_typed_id("job", j["id"]), "name": j["title"], "code": j["code"]} for j in jobs
        ],
        "roles": ["EMPLOYEE", "MANAGER"],
        "mappings": [
            {
                "kind": m["kind"],
                "external_value": m["external_value"],
                "target": m["target_value"] or str(m["target_id"]),
            }
            for m in mappings
        ],
    }


# ─── Employee sync ───────────────────────────────────────────────────────────


@router.put("/employees/{external_id}", response_model=SyncResult)
async def upsert_employee(
    external_id: str,
    body: EmployeeUpsert,
    ctx: IntegrationDep,
    dry_run: bool = Query(default=False, description="Show what would change, without saving"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=120),
):
    return await _logged(
        ctx,
        "UPSERT",
        external_id,
        lambda: service.upsert_employee(ctx, external_id, body),
        idempotency_key=None if dry_run else idempotency_key,
        payload={"external_id": external_id, **body.model_dump(mode="json", exclude_unset=True)},
        dry_run=dry_run,
        status_for=lambda r: 201 if r.outcome == "CREATED" else 200,
    )


@router.get("/employees/{external_id}")
async def get_synced_employee(external_id: str, ctx: IntegrationDep) -> dict[str, Any]:
    ctx.require("employees.read")
    identity = await service.find_identity(ctx, external_id)
    if identity is None:
        raise CodedHTTPException(
            404, "No employee is linked to this external ID", code="NOT_LINKED"
        )
    if not ctx.covers_entity(identity["legal_entity_id"]):
        raise CodedHTTPException(
            404, "No employee is linked to this external ID", code="NOT_LINKED"
        )
    document = await events.employee_snapshot(ctx.session, ctx.tenant_id, identity["employment_id"])
    settings = await effective_settings(
        ctx.session, ctx.tenant_id, ctx.app_id, identity["legal_entity_id"]
    )
    return events.filter_for_app(document, settings, ctx.app_code) or {}


@router.post("/employees/{external_id}/exit", response_model=SyncResult)
async def exit_employee(
    external_id: str,
    body: ExitRequest,
    ctx: IntegrationDep,
    idempotency_key: str = Header(alias="Idempotency-Key", max_length=120),
):
    ctx.require("employees.sync")

    async def run():
        await service.lock_external(ctx, external_id)
        ctx.session.info["integration_origin_app_id"] = ctx.app_id
        return await service.exit_employee(ctx, external_id, body)

    return await _logged(
        ctx,
        "EXIT",
        external_id,
        run,
        idempotency_key=idempotency_key,
        payload={"external_id": external_id, **body.model_dump(mode="json")},
        status_for=lambda r: 202 if r.outcome == "HELD_FOR_REVIEW" else 200,
    )


@router.post("/employees/{external_id}/rehire", response_model=SyncResult)
async def rehire_employee(
    external_id: str,
    body: RehireRequest,
    ctx: IntegrationDep,
    idempotency_key: str = Header(alias="Idempotency-Key", max_length=120),
):
    ctx.require("employees.sync")

    async def run():
        await service.lock_external(ctx, external_id)
        ctx.session.info["integration_origin_app_id"] = ctx.app_id
        return await service.rehire_employee(ctx, external_id, body)

    return await _logged(
        ctx,
        "REHIRE",
        external_id,
        run,
        idempotency_key=idempotency_key,
        payload={"external_id": external_id, **body.model_dump(mode="json")},
    )


@router.post("/employees/bulk", response_model=BulkResponse)
async def bulk_upsert(
    body: BulkRequest,
    ctx: IntegrationDep,
    idempotency_key: str = Header(alias="Idempotency-Key", max_length=120),
):
    ctx.require("employees.sync")
    request_hash = service.request_hash(body.model_dump(mode="json"))
    replay = await _replay(ctx, idempotency_key, request_hash)
    if replay is not None:
        return replay
    started = time.monotonic()
    await service.prehash_passwords(ctx, list(body.records))
    items: list[BulkItem] = []
    counts = {"CREATED": 0, "LINKED": 0, "UPDATED": 0, "NO_CHANGE": 0, "STALE_IGNORED": 0}
    failed = 0
    for record in body.records:
        record_started = time.monotonic()
        fields = record.model_dump(exclude_unset=True)
        fields.pop("external_id", None)
        upsert = EmployeeUpsert.model_validate(fields)
        try:
            async with ctx.session.begin_nested():
                result = await service.upsert_employee(ctx, record.external_id, upsert)
            result.request_id = ctx.request_id
            counts[result.outcome] = counts.get(result.outcome, 0) + 1
            items.append(
                BulkItem(
                    external_id=record.external_id,
                    status=201 if result.outcome == "CREATED" else 200,
                    result=result,
                )
            )
            await _insert_log(
                ctx.session,
                ctx,
                operation="BULK",
                external_id=record.external_id,
                employment_id=_employment_uuid(result),
                outcome=result.outcome,
                changes=result.changes,
                warnings=result.warnings,
                http_status=items[-1].status,
                duration_ms=int((time.monotonic() - record_started) * 1000),
            )
        except HTTPException as exc:
            failed += 1
            items.append(
                BulkItem(
                    external_id=record.external_id,
                    status=exc.status_code,
                    error={"code": getattr(exc, "code", "REJECTED"), "detail": exc.detail},
                )
            )
            await _log_failure(ctx, "BULK", record.external_id, exc, record_started)
    response = BulkResponse(
        results=items,
        created=counts["CREATED"] + counts["LINKED"],
        updated=counts["UPDATED"],
        unchanged=counts["NO_CHANGE"] + counts["STALE_IGNORED"],
        failed=failed,
    )
    body_json = jsonable_encoder(response)
    await _insert_log(
        ctx.session,
        ctx,
        operation="BULK_BATCH",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        outcome="COMPLETED",
        warnings=[f"{len(items)} records, {failed} failed"],
        response=body_json,
        http_status=200,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return JSONResponse(body_json)


@router.post("/employees/link")
async def link_employees(body: LinkRequest, ctx: IntegrationDep) -> dict[str, Any]:
    """Match your existing employees to HRMS employees by code (or email), once, at go-live."""
    ctx.require("employees.sync")
    s, tid = ctx.session, ctx.tenant_id
    matched, not_in_hrms, ambiguous, already = [], [], [], []
    for record in body.records:
        if await service.find_identity(ctx, record.external_id):
            already.append(record.external_id)
            continue
        clauses: list[str] = []
        params: dict[str, Any] = {"tid": tid, "app": ctx.app_id}
        if record.employee_code:
            clauses.append("lower(e.employee_number) = lower(:code)")
            params["code"] = record.employee_code
        if record.email:
            clauses.append("lower(ua.email) = lower(:email)")
            params["email"] = str(record.email)
        if not clauses:
            not_in_hrms.append(record.external_id)
            continue
        rows = (
            (
                await s.execute(
                    text(f"""
                SELECT e.id, e.employee_number, e.legal_entity_id FROM employments e
                LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
                WHERE e.tenant_id = :tid AND e.archived_at IS NULL AND ({" OR ".join(clauses)})
                  AND NOT EXISTS (SELECT 1 FROM external_identities x
                                  WHERE x.tenant_id = e.tenant_id
                                  AND x.app_id = :app AND x.employment_id = e.id)
            """),
                    params,
                )
            )
            .mappings()
            .all()
        )
        rows = [r for r in rows if ctx.covers_entity(r["legal_entity_id"])]
        if len(rows) == 1:
            matched.append(
                {
                    "external_id": record.external_id,
                    "employment_id": to_typed_id("employment", rows[0]["id"]),
                    "employee_code": rows[0]["employee_number"],
                }
            )
            if not body.dry_run:
                await service.link_identity(ctx, record.external_id, rows[0]["id"], None)
        elif rows:
            ambiguous.append(record.external_id)
        else:
            not_in_hrms.append(record.external_id)
    unmatched_hrms = (
        (
            await s.execute(
                text("""
            SELECT e.id, e.employee_number, e.legal_entity_id FROM employments e
            WHERE e.tenant_id = :tid AND e.archived_at IS NULL AND e.employment_state <> 'SEPARATED'
              AND NOT EXISTS (SELECT 1 FROM external_identities x WHERE x.tenant_id = e.tenant_id
                              AND x.app_id = :app AND x.employment_id = e.id)
            ORDER BY e.employee_number
        """),
                {"tid": tid, "app": ctx.app_id},
            )
        )
        .mappings()
        .all()
    )
    matched_ids = {m["employment_id"] for m in matched}
    report = {
        "dry_run": body.dry_run,
        "matched": matched,
        "not_in_hrms": not_in_hrms,
        "ambiguous": ambiguous,
        "already_linked": already,
        "not_in_app": [
            {
                "employment_id": to_typed_id("employment", r["id"]),
                "employee_code": r["employee_number"],
            }
            for r in unmatched_hrms
            if ctx.covers_entity(r["legal_entity_id"])
            and to_typed_id("employment", r["id"]) not in matched_ids
        ],
    }
    await _insert_log(
        s,
        ctx,
        operation="LINK",
        outcome="DRY_RUN" if body.dry_run else "LINKED",
        warnings=[
            f"{len(matched)} matched, {len(not_in_hrms)} not in HRMS, {len(ambiguous)} ambiguous"
        ],
        http_status=200,
    )
    return report


@router.post("/reconcile")
async def reconcile(body: ReconcileRequest, ctx: IntegrationDep) -> dict[str, Any]:
    """Differences between your active employees and HRMS's. Reports only; changes nothing."""
    ctx.require("employees.read")
    rows = (
        (
            await ctx.session.execute(
                text("""
            SELECT x.external_id, e.id, e.employee_number, e.employment_state, e.legal_entity_id
            FROM external_identities x
            JOIN employments e ON e.tenant_id = x.tenant_id AND e.id = x.employment_id
            WHERE x.tenant_id = :tid AND x.app_id = :app
        """),
                {"tid": ctx.tenant_id, "app": ctx.app_id},
            )
        )
        .mappings()
        .all()
    )
    rows = [r for r in rows if ctx.covers_entity(r["legal_entity_id"])]
    by_ext = {r["external_id"]: r for r in rows}
    active = set(body.active_external_ids)
    report: dict[str, Any] = {
        "in_app_not_in_hrms": sorted(active - set(by_ext)),
        "active_in_hrms_not_in_app": sorted(
            ext
            for ext, r in by_ext.items()
            if r["employment_state"] != "SEPARATED" and ext not in active
        ),
        "separated_in_hrms_active_in_app": sorted(
            ext
            for ext in active
            if ext in by_ext and by_ext[ext]["employment_state"] == "SEPARATED"
        ),
        "matched": len(active & set(by_ext)),
    }
    await _insert_log(
        ctx.session,
        ctx,
        operation="RECONCILE",
        outcome="COMPLETED",
        warnings=[
            f"{len(report['in_app_not_in_hrms'])} in app only, "
            f"{len(report['active_in_hrms_not_in_app'])} in HRMS only, "
            f"{len(report['separated_in_hrms_active_in_app'])} status mismatches"
        ],
        response=report,
        http_status=200,
    )
    return report


# ─── Employee sessions (self-service through the app) ────────────────────────


@router.post("/sessions", response_model=SessionResponse)
async def issue_session(body: SessionRequest, ctx: IntegrationDep) -> SessionResponse:
    ctx.require("sessions.issue")
    refused = CodedHTTPException(
        403, "No active employee is linked to this external ID", code="SESSION_REFUSED"
    )
    row: Any = (
        (
            await ctx.session.execute(
                text("""
            SELECT x.employment_id, e.legal_entity_id, e.employment_state, ua.id AS account_id,
                   ua.status, ua.token_epoch
            FROM external_identities x
            JOIN employments e ON e.tenant_id = x.tenant_id AND e.id = x.employment_id
            LEFT JOIN user_accounts ua ON ua.tenant_id = e.tenant_id AND ua.employment_id = e.id
            WHERE x.tenant_id = :tid AND x.app_id = :app AND x.external_id = :ext
        """),
                {"tid": ctx.tenant_id, "app": ctx.app_id, "ext": body.external_id},
            )
        )
        .mappings()
        .first()
    )
    if row is not None and row["account_id"] is None and row["employment_state"] != "SEPARATED":
        # Hired in HRMS without a login yet: give them one to use through the app. It has no
        # password, so it can't sign in to HRMS directly until HR issues credentials.
        account_id = await _passwordless_login(ctx, row["employment_id"])
        row = {**row, "account_id": account_id, "status": "ACTIVE", "token_epoch": 0}
    # One answer for every refusal, so the endpoint can't be used to learn who exists.
    if (
        row is None
        or row["account_id"] is None
        or row["status"] != "ACTIVE"
        or row["employment_state"] == "SEPARATED"
        or not ctx.covers_entity(row["legal_entity_id"])
    ):
        INTEGRATION_SESSIONS.labels(ctx.app_code, "refused").inc()
        raise refused
    roles = (
        await ctx.session.execute(
            text("""
            SELECT DISTINCT r.name FROM role_assignments ra
            JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
            WHERE ra.tenant_id = :tid AND ra.user_account_id = :uid
              AND r.name IN ('EMPLOYEE', 'MANAGER')
              AND (ra.expires_at IS NULL OR ra.expires_at > now())
        """),
            {"tid": ctx.tenant_id, "uid": row["account_id"]},
        )
    ).scalars().all() or ["EMPLOYEE"]
    settings = await effective_settings(
        ctx.session, ctx.tenant_id, ctx.app_id, row["legal_entity_id"]
    )
    minutes = settings.self_service.session_minutes
    token = create_access_token(
        user_account_id=row["account_id"],
        tenant_id=ctx.tenant_id,
        employment_id=row["employment_id"],
        role_names=sorted(roles),
        expires_minutes=minutes,
        token_epoch=row["token_epoch"],
        extra_claims={"via": str(ctx.key_id), "ext": ctx.app_code, "amr": ["integration"]},
    )
    await _insert_log(
        ctx.session,
        ctx,
        operation="SESSION",
        external_id=body.external_id,
        employment_id=row["employment_id"],
        outcome="ISSUED",
        http_status=200,
    )
    INTEGRATION_SESSIONS.labels(ctx.app_code, "issued").inc()
    return SessionResponse(
        access_token=token,
        expires_in=minutes * 60,
        employment_id=to_typed_id("employment", row["employment_id"]),
        roles=sorted(roles),
    )


async def _passwordless_login(ctx: IntegrationContext, employment_id: UUID) -> UUID:
    from hrms.modules.kernel.models import UserAccount

    code = (
        await ctx.session.execute(
            text("SELECT employee_number FROM employments WHERE tenant_id = :tid AND id = :eid"),
            {"tid": ctx.tenant_id, "eid": employment_id},
        )
    ).scalar()
    account = UserAccount(
        tenant_id=ctx.tenant_id,
        id=uuid4(),
        employee_code=code,
        password_hash=None,
        employment_id=employment_id,
        status="ACTIVE",
    )
    ctx.session.add(account)
    await ctx.session.flush()
    await service._set_role(ctx, account.id, "EMPLOYEE")
    await ctx.session.execute(
        text("""UPDATE external_identities SET user_account_id = :uid
                WHERE tenant_id = :tid AND app_id = :app AND employment_id = :eid"""),
        {"uid": account.id, "tid": ctx.tenant_id, "app": ctx.app_id, "eid": employment_id},
    )
    return account.id


# ─── Read API ────────────────────────────────────────────────────────────────


@router.get("/events", response_model=FeedResponse)
async def events_feed(
    ctx: IntegrationDep,
    after: str | None = Query(default=None, description="The next_cursor from your last call"),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    ctx.require("events.read")
    # Release held events whose time has come in their own committed transaction, so this read
    # can already return them (the feed only shows rows from finished transactions).
    async with database.AsyncSessionLocal() as release:
        await release.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(ctx.tenant_id)}
        )
        if await events.release_due(release, ctx.tenant_id, ctx.app_id):
            await release.commit()
    return await events.read_feed(
        ctx.session,
        ctx.tenant_id,
        ctx.app_id,
        ctx.app_code,
        events.decode_cursor(after),
        limit,
        legal_entity_ids=ctx.legal_entity_ids,
    )


@router.get("/employees")
async def list_synced_employees(
    ctx: IntegrationDep,
    updated_since: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None, description="next_cursor from the previous page"),
    limit: int = Query(default=100, ge=1, le=200),
    include_separated: bool = Query(default=False),
) -> dict[str, Any]:
    ctx.require("employees.read")
    where = ["e.tenant_id = :tid", "e.archived_at IS NULL"]
    params: dict[str, Any] = {"tid": ctx.tenant_id, "limit": limit + 1, "today": business_today()}
    if not include_separated:
        where.append("e.employment_state <> 'SEPARATED'")
    if cursor:
        where.append("e.id > :after")
        params["after"] = to_uuid(cursor)
    if updated_since is not None:
        where.append("""EXISTS (SELECT 1 FROM integration_events ev WHERE ev.tenant_id = e.tenant_id
                        AND ev.employment_id = e.id AND ev.occurred_at > :since)""")
        params["since"] = updated_since
    if ctx.legal_entity_ids is not None:
        where.append("e.legal_entity_id = ANY(CAST(:entities AS uuid[]))")
        params["entities"] = [str(i) for i in ctx.legal_entity_ids]
    rows = (
        (
            await ctx.session.execute(
                text(
                    f"{events.SNAPSHOT_SQL} WHERE {' AND '.join(where)} ORDER BY e.id LIMIT :limit"
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    out, settings_cache = [], {}
    for r in rows:
        le = r["legal_entity_id"]
        if le not in settings_cache:
            settings_cache[le] = await effective_settings(
                ctx.session, ctx.tenant_id, ctx.app_id, le
            )
        document = events.snapshot_from_row(r)
        if events.in_people(settings_cache[le], document):
            out.append(events.filter_for_app(document, settings_cache[le], ctx.app_code))
    latest = (
        await ctx.session.execute(
            text("""SELECT GREATEST(
                        COALESCE((SELECT MAX(seq) FROM integration_app_events
                                  WHERE tenant_id = :tid AND app_id = :app AND seq IS NOT NULL), 0),
                        COALESCE((SELECT purged_through FROM integration_cursors
                                  WHERE tenant_id = :tid AND app_id = :app), 0))"""),
            {"tid": ctx.tenant_id, "app": ctx.app_id},
        )
    ).scalar_one()
    return {
        "employees": out,
        "next_cursor": to_typed_id("employment", rows[-1]["employment_id"]) if has_more else None,
        "has_more": has_more,
        # After a full reload, continue the events feed from here.
        "events_cursor": events.encode_cursor(latest),
    }


@router.get("/org/{kind}")
async def org_reference(kind: str, ctx: IntegrationDep) -> list[dict[str, Any]]:
    ctx.require("org.read")
    queries = {
        "companies": (
            """SELECT id, name, short_name AS code FROM legal_entities
                         WHERE tenant_id = :tid AND archived_at IS NULL ORDER BY name""",
            "legal_entity",
        ),
        "departments": (
            """SELECT id, name, code, type, legal_entity_id FROM org_units
                           WHERE tenant_id = :tid AND archived_at IS NULL
                             AND type <> 'DEPARTMENT_TEMPLATE' ORDER BY name""",
            "org_unit",
        ),
        "locations": (
            """SELECT id, name, city, legal_entity_id FROM locations
                         WHERE tenant_id = :tid ORDER BY name""",
            "location",
        ),
        "designations": (
            """SELECT id, title AS name, code FROM jobs
                            WHERE tenant_id = :tid AND archived_at IS NULL ORDER BY title""",
            "job",
        ),
    }
    if kind not in queries:
        raise HTTPException(
            404, "Unknown list. Use companies, departments, locations or designations."
        )
    sql, prefix = queries[kind]
    rows = (await ctx.session.execute(text(sql), {"tid": ctx.tenant_id})).mappings().all()
    out = []
    for r in rows:
        item = {k: v for k, v in r.items() if k not in ("id", "legal_entity_id")}
        item["id"] = to_typed_id(prefix, r["id"])
        if "legal_entity_id" in r:
            if r["legal_entity_id"] and not ctx.covers_entity(r["legal_entity_id"]):
                continue
            item["company_id"] = (
                to_typed_id("legal_entity", r["legal_entity_id"]) if r["legal_entity_id"] else None
            )
        elif prefix == "legal_entity" and not ctx.covers_entity(r["id"]):
            continue
        out.append(item)
    return out


@router.get("/holidays")
async def holidays(ctx: IntegrationDep, year: int = Query(ge=2000, le=2100)) -> dict[str, Any]:
    ctx.require("org.read")
    calendars = (
        (
            await ctx.session.execute(
                text("""
            SELECT c.id, c.name, h.holiday_date, h.name AS holiday, d.is_optional
            FROM holiday_calendars c
            JOIN holiday_calendar_days d ON d.tenant_id = c.tenant_id AND d.calendar_id = c.id
            JOIN holidays h ON h.tenant_id = d.tenant_id AND h.id = d.holiday_id
            WHERE c.tenant_id = :tid AND c.archived_at IS NULL AND c.year = :year
              AND h.archived_at IS NULL
            ORDER BY c.name, h.holiday_date
        """),
                {"tid": ctx.tenant_id, "year": year},
            )
        )
        .mappings()
        .all()
    )
    assignments = (
        (
            await ctx.session.execute(
                text("""
            SELECT a.calendar_id, a.legal_entity_id, a.org_unit_id, a.employment_id
            FROM holiday_calendar_assignments a
            JOIN holiday_calendars c ON c.tenant_id = a.tenant_id AND c.id = a.calendar_id
            WHERE a.tenant_id = :tid AND c.year = :year
        """),
                {"tid": ctx.tenant_id, "year": year},
            )
        )
        .mappings()
        .all()
    )
    by_calendar: dict[UUID, dict[str, Any]] = {}
    for r in calendars:
        cal = by_calendar.setdefault(
            r["id"],
            {
                "id": to_typed_id("holiday_calendar", r["id"]),
                "name": r["name"],
                "holidays": [],
                "applies_to": [],
            },
        )
        cal["holidays"].append(
            {
                "date": r["holiday_date"].isoformat(),
                "name": r["holiday"],
                "optional": r["is_optional"],
            }
        )
    for a in assignments:
        if a["calendar_id"] not in by_calendar:
            continue
        cal = by_calendar[a["calendar_id"]]
        if a["employment_id"]:
            cal["applies_to"].append(
                {"employment_id": to_typed_id("employment", a["employment_id"])}
            )
        elif a["org_unit_id"]:
            cal["applies_to"].append({"department_id": to_typed_id("org_unit", a["org_unit_id"])})
        elif a["legal_entity_id"]:
            cal["applies_to"].append(
                {"company_id": to_typed_id("legal_entity", a["legal_entity_id"])}
            )
    return {"year": year, "calendars": list(by_calendar.values())}


async def _people_filter(ctx: IntegrationContext) -> tuple[str, dict[str, Any]]:
    if ctx.legal_entity_ids is None:
        return "", {}
    return (
        "AND e.legal_entity_id = ANY(CAST(:entities AS uuid[]))",
        {"entities": [str(i) for i in ctx.legal_entity_ids]},
    )


@router.get("/leave")
async def approved_leave(
    ctx: IntegrationDep,
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
) -> list[dict[str, Any]]:
    ctx.require("leave.read")
    if (to_date - from_date).days > 366 or to_date < from_date:
        raise HTTPException(422, "The range must be at most a year, and 'to' on or after 'from'")
    clause, params = await _people_filter(ctx)
    rows = (
        (
            await ctx.session.execute(
                text(f"""
            SELECT la.id, la.employment_id, e.employee_number, lt.name AS leave_type,
                   la.from_date, la.to_date, la.days_requested, la.half_day_option,
                   (SELECT x.external_id FROM external_identities x WHERE x.tenant_id = la.tenant_id
                      AND x.app_id = :app AND x.employment_id = la.employment_id) AS external_id
            FROM leave_applications la
            JOIN employments e ON e.tenant_id = la.tenant_id AND e.id = la.employment_id
            JOIN leave_types lt ON lt.tenant_id = la.tenant_id AND lt.id = la.leave_type_id
            WHERE la.tenant_id = :tid AND la.status = 'APPROVED' AND la.archived_at IS NULL
              AND la.from_date <= :to AND la.to_date >= :from {clause}
            ORDER BY la.from_date, e.employee_number
        """),
                {
                    "tid": ctx.tenant_id,
                    "app": ctx.app_id,
                    "from": from_date,
                    "to": to_date,
                    **params,
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": to_typed_id("leave_application", r["id"]),
            "employment_id": to_typed_id("employment", r["employment_id"]),
            "external_id": r["external_id"],
            "employee_code": r["employee_number"],
            "leave_type": r["leave_type"],
            "from": r["from_date"].isoformat(),
            "to": r["to_date"].isoformat(),
            "days": float(r["days_requested"]),
            "half_day": r["half_day_option"],
        }
        for r in rows
    ]


@router.get("/attendance/daily")
async def daily_attendance(
    ctx: IntegrationDep, on: date = Query(alias="date")
) -> list[dict[str, Any]]:
    ctx.require("attendance.read")
    clause, params = await _people_filter(ctx)
    rows = (
        (
            await ctx.session.execute(
                text(f"""
            SELECT ad.employment_id, e.employee_number, ad.status, ad.first_punch_in,
                   ad.last_punch_out, ad.effective_minutes,
                   (SELECT x.external_id FROM external_identities x WHERE x.tenant_id = ad.tenant_id
                      AND x.app_id = :app AND x.employment_id = ad.employment_id) AS external_id
            FROM attendance_days ad
            JOIN employments e ON e.tenant_id = ad.tenant_id AND e.id = ad.employment_id
            WHERE ad.tenant_id = :tid AND ad.work_date = :on {clause}
            ORDER BY e.employee_number
        """),
                {"tid": ctx.tenant_id, "app": ctx.app_id, "on": on, **params},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "employment_id": to_typed_id("employment", r["employment_id"]),
            "external_id": r["external_id"],
            "employee_code": r["employee_number"],
            "date": on.isoformat(),
            "status": r["status"],
            "first_in": r["first_punch_in"].isoformat() if r["first_punch_in"] else None,
            "last_out": r["last_punch_out"].isoformat() if r["last_punch_out"] else None,
            "worked_minutes": r["effective_minutes"],
        }
        for r in rows
    ]

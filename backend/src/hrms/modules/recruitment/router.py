"""
Recruitment.

Access & config  GET  /v1/recruitment/access          what the caller may do + form lookups
                 GET  /v1/recruitment/stages          the tenant's candidate pipeline
                 PUT  /v1/recruitment/stages          replace it (all-company recruiters)
Openings         GET/POST            /v1/recruitment/openings
                 GET/PUT/DELETE      /v1/recruitment/openings/{id}
                 POST                /v1/recruitment/openings/{id}/{submit,withdraw,decision,status}
                 GET                 /v1/recruitment/openings/{id}/events
Pipeline         GET/POST            /v1/recruitment/openings/{id}/applications
                 GET/PATCH           /v1/recruitment/applications/{id}
                 POST                /v1/recruitment/applications/{id}/move | notes | hire
Talent pool      GET                 /v1/recruitment/candidates
                 GET/PUT/DELETE      /v1/recruitment/candidates/{id}
                 POST/GET/DELETE     /v1/recruitment/candidates/{id}/resume

Openings raised by people without recruiter rights go through the approval flow
configured for JOB_REQUISITION (Settings → Approval flows) for the requester's team,
or — with no flow — through anyone holding `recruitment.approve` for that company.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core import document_store
from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep
from hrms.core.config import settings
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import now_utc
from hrms.core.ids import to_typed_id
from hrms.core.tenancy import TenantDep
from hrms.modules.approvals import service as approval_flow
from hrms.modules.recruitment import service as svc
from hrms.modules.recruitment.access import Access, load_access
from hrms.modules.recruitment.models import (
    Candidate,
    JobApplication,
    JobOpening,
    OpeningStatus,
    RecruitmentStage,
    StageCategory,
)
from hrms.modules.recruitment.schemas import (
    ApplicationCreate,
    ApplicationDetail,
    ApplicationHire,
    ApplicationMove,
    ApplicationSummary,
    ApplicationUpdate,
    CandidateInput,
    CandidateResponse,
    EventResponse,
    NoteCreate,
    OpeningDecision,
    OpeningDetail,
    OpeningInput,
    OpeningStatusChange,
    OpeningSummary,
    RecruitmentAccess,
    StageResponse,
    StagesUpdate,
)

router = APIRouter(prefix="/v1/recruitment", tags=["Recruitment"])

KIND = svc.APPROVAL_KIND
EDITABLE_BY_REQUESTER = {OpeningStatus.DRAFT, OpeningStatus.REJECTED}
LIVE = {OpeningStatus.OPEN, OpeningStatus.ON_HOLD, OpeningStatus.FILLED}
RESUME_TYPES = {
    b"%PDF-": ("application/pdf", (".pdf",)),
    b"PK\x03\x04": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        (".docx",),
    ),
    b"\xd0\xcf\x11\xe0": ("application/msword", (".doc",)),
}


async def _access(session, tenant_id, principal, scope) -> Access:
    return await load_access(session, tenant_id, principal, scope)


def _now() -> datetime:
    return datetime.now(UTC)


# ─── Access & lookups ───────────────────────────────────────────────────────


@router.get("/access", response_model=RecruitmentAccess)
async def access(
    principal: CurrentUser, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
) -> RecruitmentAccess:
    acc = await _access(session, tenant_id, principal, scope)
    departments: list[dict] = []
    if acc.can_request:
        clauses = ["ou.id = ANY(:led)"]
        params: dict = {"tid": tenant_id, "led": list(acc.led_units)}
        if acc.own_unit and acc.request_role:
            clauses.append("ou.id = :own")
            params["own"] = acc.own_unit
        if acc.manage is not None:
            if acc.manage.is_all:
                clauses.append("TRUE")
            else:
                clauses.append("ou.legal_entity_id = ANY(:entities)")
                clauses.append("ou.id = ANY(:units)")
                params["entities"] = list(acc.manage.legal_entity_ids)
                params["units"] = list(acc.manage.org_unit_ids)
        rows = await session.execute(
            text(f"""
                SELECT ou.id, ou.name, ou.type, ou.legal_entity_id, le.name AS company
                FROM org_units ou
                LEFT JOIN legal_entities le
                    ON le.tenant_id = ou.tenant_id AND le.id = ou.legal_entity_id
                WHERE ou.tenant_id = :tid AND ou.status = 'ACTIVE' AND ou.archived_at IS NULL
                  AND ou.legal_entity_id IS NOT NULL AND ({" OR ".join(clauses)})
                ORDER BY le.name, ou.name
                LIMIT 1000
            """),
            params,
        )
        departments = [
            dict(
                id=to_typed_id("org_unit", r.id),
                name=r.name,
                legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id),
                detail=f"{(r.type or '').title()} · {r.company}" if r.company else r.type,
            )
            for r in rows
        ]
    jobs, locations, managers = [], [], []
    if departments:
        jobs = [
            dict(id=to_typed_id("job", r.id), name=r.title)
            for r in await session.execute(
                text("""SELECT id, title FROM jobs WHERE tenant_id = :tid AND status = 'ACTIVE'
                        ORDER BY title LIMIT 1000"""),
                {"tid": tenant_id},
            )
        ]
        locations = [
            dict(
                id=to_typed_id("location", r.id),
                name=r.name,
                legal_entity_id=svc.typed("legal_entity", r.legal_entity_id),
            )
            for r in await session.execute(
                text("""SELECT id, name, legal_entity_id FROM locations
                        WHERE tenant_id = :tid AND status = 'ACTIVE' ORDER BY name LIMIT 1000"""),
                {"tid": tenant_id},
            )
        ]
        # Hiring managers: the leaders of the units on offer, and the caller.
        unit_ids = [svc.parse_id(d["id"]) for d in departments]
        rows = await session.execute(
            text("""
                SELECT DISTINCT e.id, p.legal_first_name || ' ' || p.legal_last_name AS name,
                       e.employee_number, e.legal_entity_id
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                WHERE e.tenant_id = :tid AND (e.id = :me OR e.id IN (
                    SELECT unnest(ARRAY[head_employment_id, lead_employment_id, pm_employment_id])
                    FROM org_units WHERE tenant_id = :tid AND id = ANY(:units)))
                ORDER BY name
            """),
            {"tid": tenant_id, "me": acc.employment_id, "units": unit_ids},
        )
        managers = [
            dict(
                id=to_typed_id("employment", r.id),
                name=r.name,
                legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id),
                detail=r.employee_number,
            )
            for r in rows
        ]
    return RecruitmentAccess(
        can_request=acc.can_request,
        can_manage=acc.can_manage_any,
        can_approve=acc.approve is not None,
        departments=departments,
        jobs=jobs,
        locations=locations,
        hiring_managers=managers,
    )


# ─── Pipeline stages ────────────────────────────────────────────────────────


@router.get("/stages", response_model=list[StageResponse])
async def get_stages(
    principal: CurrentUser, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
) -> list[dict]:
    acc = await _access(session, tenant_id, principal, scope)
    if not (acc.can_request or acc.read is not None):
        raise HTTPException(403, "You don’t have access to recruitment")
    return [svc.stage_public(s) for s in await svc.ensure_stages(session, tenant_id)]


@router.put("/stages", response_model=list[StageResponse])
async def put_stages(
    body: StagesUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[dict]:
    acc = await _access(session, tenant_id, principal, scope)
    if not acc.manages_pipeline:
        raise HTTPException(403, "Changing the pipeline needs recruiter access to every company")
    existing = {s.id: s for s in await svc.ensure_stages(session, tenant_id)}
    await svc.lock_resource(session, tenant_id, "recruitment-stages")
    original_names = {uid: stage.name for uid, stage in existing.items()}
    kept: set[UUID] = set()
    # Free the names first so a rename/swap can't trip the unique name index mid-way.
    for stage in existing.values():
        stage.name = f"~{stage.id}"[:60]
        session.add(stage)
    await session.flush()
    for i, item in enumerate(body.stages):
        uid = svc.parse_id(item.id, "stage")
        if uid is not None:
            stage = existing.get(uid)
            if stage is None:
                raise HTTPException(422, f"Unknown stage “{item.name}”")
            if stage.category != item.category:
                in_use = (
                    await session.execute(
                        text("""SELECT count(*) FROM job_applications
                                WHERE tenant_id = :tid AND stage_id = :sid"""),
                        {"tid": tenant_id, "sid": uid},
                    )
                ).scalar()
                if in_use:
                    raise HTTPException(
                        409,
                        f"“{item.name}” has candidates in it, so its outcome can’t change. "
                        "Add a new stage instead.",
                    )
            stage.version += 1
        else:
            stage = RecruitmentStage(tenant_id=tenant_id, id=uuid4())
        stage.name, stage.category, stage.color = item.name, item.category, item.color
        stage.sequence, stage.is_active, stage.updated_at = i, item.is_active, _now()
        session.add(stage)
        kept.add(stage.id)
    for uid, stage in existing.items():
        if uid in kept:
            continue
        # Stages are never deleted (applications and history point at them); one left out
        # of the list is deactivated and parked at the end under a name that can't clash.
        stage.is_active = False
        stage.sequence = 1000 + i + stage.sequence
        stage.name = f"{original_names[uid][:44]} (archived {str(uid)[:4]})"
        stage.version += 1
        stage.updated_at = _now()
        session.add(stage)
    await session.flush()
    return [svc.stage_public(s) for s in await svc.list_stages(session, tenant_id)]


# ─── Openings ───────────────────────────────────────────────────────────────


async def _apply_input(session, tenant_id, acc: Access, opening: JobOpening, body: OpeningInput):
    unit = svc.parse_id(body.org_unit_id, "department")
    entity = await svc.unit_entity(session, tenant_id, unit)
    if not acc.may_raise_for(unit, entity):
        raise HTTPException(403, "You can only raise openings for teams you lead or recruit for")
    job = svc.parse_id(body.job_id, "designation")
    location = svc.parse_id(body.location_id, "location")
    manager = svc.parse_id(body.hiring_manager_employment_id, "hiring manager")
    await svc.check_reference(session, tenant_id, "jobs", job, "designation")
    await svc.check_reference(session, tenant_id, "locations", location, "location", entity)
    await svc.check_reference(session, tenant_id, "employments", manager, "hiring manager")
    opening.title = body.title
    opening.org_unit_id, opening.legal_entity_id = unit, entity
    opening.job_id, opening.location_id = job, location
    opening.hiring_manager_employment_id = manager or opening.requester_employment_id
    for field in (
        "employment_type",
        "work_mode",
        "positions",
        "priority",
        "reason",
        "min_experience_years",
        "max_experience_years",
        "salary_min",
        "salary_max",
        "currency",
        "target_start_date",
        "description",
        "responsibilities",
        "requirements",
        "skills",
    ):
        setattr(opening, field, getattr(body, field))
    opening.replacement_for = body.replacement_for if body.reason == "REPLACEMENT" else None


def _flow_participant(instance, principal) -> bool:
    """Approvers named on the opening's approval route may read it while they decide."""
    return instance is not None and any(
        str(principal.user_account_id) in step.get("approver_ids", []) for step in instance.steps
    )


async def _detail(session, tenant_id, acc: Access, principal, opening_id: UUID) -> dict:
    rows = await svc.opening_rows(session, tenant_id, "AND o.id = :oid", {"oid": opening_id})
    if not rows:
        raise HTTPException(404, "Opening not found")
    row = rows[0]
    instance = await approval_flow.current_instance(session, tenant_id, KIND, row.id)
    if not acc.can_view(row) and not _flow_participant(instance, principal):
        raise HTTPException(404, "Opening not found")
    stages = {s.id: s for s in await svc.ensure_stages(session, tenant_id)}
    counts = (await svc.stage_counts(session, tenant_id, [row.id])).get(row.id, {})
    summary = svc.opening_summary(row, counts, stages)
    approved_by = (await svc.user_names(session, tenant_id, [row.approved_by])).get(row.approved_by)
    manages = acc.manages(row)
    is_requester = row.requested_by == acc.user_id
    can_decide = False
    if row.status == OpeningStatus.PENDING_APPROVAL:
        if row.approval_mode == "FLOW" and instance is not None and instance.status == "PENDING":
            try:
                await approval_flow.actor_for(session, tenant_id, instance, principal)
                can_decide = True
            except HTTPException:
                can_decide = False
        elif row.approval_mode == "HR":
            can_decide = acc.approves(row) and not is_requester
    status = OpeningStatus(row.status)
    return dict(
        **summary,
        job_id=svc.typed("job", row.job_id),
        location_id=svc.typed("location", row.location_id),
        reason=row.reason,
        replacement_for=row.replacement_for,
        min_experience_years=row.min_experience_years,
        max_experience_years=row.max_experience_years,
        salary_min=row.salary_min,
        salary_max=row.salary_max,
        currency=row.currency,
        description=row.description,
        responsibilities=row.responsibilities,
        requirements=row.requirements,
        skills=row.skills or [],
        approval_mode=row.approval_mode,
        approval_instance_id=svc.typed("approval_instance", instance.id) if instance else None,
        approved_at=row.approved_at,
        approved_by_name=approved_by,
        decision_comment=row.decision_comment,
        closed_at=row.closed_at,
        close_reason=row.close_reason,
        version=row.version,
        can_edit=(status in EDITABLE_BY_REQUESTER and (is_requester or manages))
        or (status in (OpeningStatus.OPEN, OpeningStatus.ON_HOLD) and manages),
        can_submit=status in EDITABLE_BY_REQUESTER and (is_requester or manages),
        can_withdraw=status == OpeningStatus.PENDING_APPROVAL and (is_requester or manages),
        can_decide=can_decide,
        can_manage=manages,
    )


@router.get("/openings", response_model=list[OpeningSummary])
async def list_openings(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    status: str | None = Query(None, description="Comma-separated statuses"),
    q: str | None = Query(None, max_length=100),
    mine: bool = False,
) -> list[dict]:
    acc = await _access(session, tenant_id, principal, scope)
    where, params = acc.opening_filter_sql("o")
    if status:
        wanted = [s.strip().upper() for s in status.split(",") if s.strip()]
        where += " AND o.status = ANY(:statuses)"
        params["statuses"] = wanted
    if q and q.strip():
        where += " AND (o.title ILIKE :q OR o.code ILIKE :q)"
        params["q"] = f"%{q.strip()}%"
    if mine:
        where += " AND (o.requested_by = :me_uid OR o.hiring_manager_employment_id = :me_eid)"
        params.update(me_uid=acc.user_id, me_eid=acc.employment_id)
    rows = await svc.opening_rows(session, tenant_id, where, params)
    stages = {s.id: s for s in await svc.ensure_stages(session, tenant_id)}
    counts = await svc.stage_counts(session, tenant_id, [r.id for r in rows])
    return [svc.opening_summary(r, counts.get(r.id, {}), stages) for r in rows]


@router.post("/openings", response_model=OpeningDetail, status_code=201)
async def create_opening(
    body: OpeningInput,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    submit: bool = Query(False, description="Submit for approval straight away"),
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    if not acc.can_request:
        raise HTTPException(403, "Only department heads, team leads, PMs and HR can raise openings")
    opening = JobOpening(
        tenant_id=tenant_id,
        id=uuid4(),
        code=await svc.next_code(session, tenant_id),
        title=body.title,
        legal_entity_id=uuid4(),  # set by _apply_input
        org_unit_id=uuid4(),
        requested_by=principal.user_account_id,
        requester_employment_id=principal.employment_id,
        employment_type=body.employment_type,
        work_mode=body.work_mode,
        priority=body.priority,
        reason=body.reason,
        description=body.description,
        status=OpeningStatus.DRAFT,
    )
    await _apply_input(session, tenant_id, acc, opening, body)
    session.add(opening)
    await session.flush()
    await svc.event(
        session, tenant_id, opening.id, principal.user_account_id, "CREATED", {"code": opening.code}
    )
    if submit:
        await _submit(session, tenant_id, acc, principal, opening)
    await session.flush()
    return await _detail(session, tenant_id, acc, principal, opening.id)


@router.get("/openings/{opening_id}", response_model=OpeningDetail)
async def get_opening(
    opening_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    return await _detail(session, tenant_id, acc, principal, svc.parse_id(opening_id, "opening"))


class _OpeningUpdate(OpeningInput):
    version: int


@router.put("/openings/{opening_id}", response_model=OpeningDetail)
async def update_opening(
    opening_id: str,
    body: _OpeningUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id, lock=True)
    acc.require_view(opening)
    status = OpeningStatus(opening.status)
    allowed = (
        status in EDITABLE_BY_REQUESTER
        and (opening.requested_by == principal.user_account_id or acc.manages(opening))
    ) or (status in (OpeningStatus.OPEN, OpeningStatus.ON_HOLD) and acc.manages(opening))
    if not allowed:
        raise HTTPException(
            409 if status == OpeningStatus.PENDING_APPROVAL else 403,
            "Withdraw the opening from approval before editing it"
            if status == OpeningStatus.PENDING_APPROVAL
            else "You can’t edit this opening in its current state",
        )
    if body.version != opening.version:
        raise HTTPException(409, "Someone else changed this opening — reload and try again")
    before = {"title": opening.title, "positions": opening.positions}
    await _apply_input(session, tenant_id, acc, opening, body)
    opening.version += 1
    opening.updated_at = _now()
    session.add(opening)
    await svc.event(
        session,
        tenant_id,
        opening.id,
        principal.user_account_id,
        "UPDATED",
        {"before": before, "after": {"title": opening.title, "positions": opening.positions}},
    )
    await _sync_filled(session, tenant_id, opening, principal.user_account_id)
    await session.flush()
    return await _detail(session, tenant_id, acc, principal, opening.id)


@router.delete("/openings/{opening_id}", status_code=204)
async def delete_opening(
    opening_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id, lock=True)
    acc.require_view(opening)
    if opening.status not in EDITABLE_BY_REQUESTER:
        raise HTTPException(
            409, "Only draft or rejected openings can be deleted — close it instead"
        )
    if not (opening.requested_by == principal.user_account_id or acc.manages(opening)):
        raise HTTPException(403, "Only the requester or a recruiter can delete this opening")
    await session.delete(opening)
    await session.flush()


async def _submit(session, tenant_id, acc: Access, principal, opening: JobOpening) -> None:
    if opening.status not in EDITABLE_BY_REQUESTER:
        raise HTTPException(409, "This opening has already been submitted")
    if not (opening.requested_by == principal.user_account_id or acc.manages(opening)):
        raise HTTPException(403, "Only the requester or a recruiter can submit this opening")
    route = None
    if opening.requester_employment_id is not None:
        route = await approval_flow.start(
            session,
            tenant_id,
            KIND,
            opening.id,
            opening.requester_employment_id,
            {"code": opening.code, "title": opening.title, "positions": opening.positions},
        )
    now = _now()
    opening.submitted_at = now
    opening.decision_comment = None
    if route is not None:
        opening.status, opening.approval_mode = OpeningStatus.PENDING_APPROVAL, "FLOW"
        await svc.event(
            session,
            tenant_id,
            opening.id,
            principal.user_account_id,
            "SUBMITTED",
            {"mode": "FLOW", "stages": [s["name"] for s in route.steps]},
        )
    elif acc.approves(opening):
        # A recruiter who may approve this company's openings doesn't approve themselves
        # through a queue: the opening goes live, and the history says who did it.
        opening.status, opening.approval_mode = OpeningStatus.OPEN, "AUTO"
        opening.approved_at, opening.approved_by = now, principal.user_account_id
        await svc.event(
            session, tenant_id, opening.id, principal.user_account_id, "APPROVED", {"mode": "AUTO"}
        )
    else:
        opening.status, opening.approval_mode = OpeningStatus.PENDING_APPROVAL, "HR"
        await svc.event(
            session, tenant_id, opening.id, principal.user_account_id, "SUBMITTED", {"mode": "HR"}
        )
    opening.version += 1
    opening.updated_at = now
    session.add(opening)


@router.post("/openings/{opening_id}/submit", response_model=OpeningDetail)
async def submit_opening(
    opening_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id, lock=True)
    acc.require_view(opening)
    await _submit(session, tenant_id, acc, principal, opening)
    await session.flush()
    return await _detail(session, tenant_id, acc, principal, opening.id)


@router.post("/openings/{opening_id}/withdraw", response_model=OpeningDetail)
async def withdraw_opening(
    opening_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id, lock=True)
    acc.require_view(opening)
    if opening.status != OpeningStatus.PENDING_APPROVAL:
        raise HTTPException(409, "Only an opening awaiting approval can be withdrawn")
    if not (opening.requested_by == principal.user_account_id or acc.manages(opening)):
        raise HTTPException(403, "Only the requester or a recruiter can withdraw this opening")
    await approval_flow.finish(session, tenant_id, KIND, opening.id, "CANCELLED")
    opening.status, opening.approval_mode, opening.submitted_at = OpeningStatus.DRAFT, None, None
    opening.version += 1
    opening.updated_at = _now()
    session.add(opening)
    await svc.event(session, tenant_id, opening.id, principal.user_account_id, "WITHDRAWN")
    await session.flush()
    return await _detail(session, tenant_id, acc, principal, opening.id)


async def decide(
    session, tenant_id, principal, scope, opening: JobOpening, action: str, comments: str | None
) -> None:
    """Approve or reject a pending opening; used here and by the shared approvals inbox."""
    acc = await _access(session, tenant_id, principal, scope)
    if opening.status != OpeningStatus.PENDING_APPROVAL:
        raise HTTPException(409, "This opening isn’t awaiting approval")
    comments = (comments or "").strip() or None
    level_name = None
    if opening.approval_mode == "FLOW":
        instance = await approval_flow.current_instance(session, tenant_id, KIND, opening.id)
        if instance is None or instance.status != "PENDING":
            raise HTTPException(409, "This opening’s approval route is no longer pending")
        level_name = instance.steps[instance.current_level - 1]["name"]
        final = await approval_flow.record_decision(
            session, tenant_id, KIND, opening.id, principal, action, comments
        )
    else:
        acc.require_view(opening)
        if not acc.approves(opening):
            raise HTTPException(403, "You can’t approve openings for this company")
        if opening.requested_by == principal.user_account_id:
            raise HTTPException(403, "Someone other than the requester must approve it")
        final = True
    now = _now()
    if action == "REJECT":
        opening.status = OpeningStatus.REJECTED
        opening.decision_comment = comments
        await svc.event(
            session,
            tenant_id,
            opening.id,
            principal.user_account_id,
            "REJECTED",
            {"comments": comments, "stage": level_name},
        )
    else:
        await svc.event(
            session,
            tenant_id,
            opening.id,
            principal.user_account_id,
            "APPROVED" if final else "APPROVAL_STEP",
            {"comments": comments, "stage": level_name, "mode": opening.approval_mode},
        )
        if final:
            opening.status = OpeningStatus.OPEN
            opening.approved_at, opening.approved_by = now, principal.user_account_id
            opening.decision_comment = comments
    opening.version += 1
    opening.updated_at = now
    session.add(opening)


@router.post("/openings/{opening_id}/decision", response_model=OpeningDetail)
async def decide_opening(
    opening_id: str,
    body: OpeningDecision,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    opening = await svc.get_opening(session, tenant_id, opening_id, lock=True)
    await decide(session, tenant_id, principal, scope, opening, body.action, body.comments)
    await session.flush()
    acc = await _access(session, tenant_id, principal, scope)
    return await _detail(session, tenant_id, acc, principal, opening.id)


@router.post("/openings/{opening_id}/status", response_model=OpeningDetail)
async def change_status(
    opening_id: str,
    body: OpeningStatusChange,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id, lock=True)
    acc.require_manage(opening)
    allowed = {
        OpeningStatus.OPEN: {OpeningStatus.ON_HOLD, OpeningStatus.CLOSED},
        OpeningStatus.ON_HOLD: {OpeningStatus.OPEN, OpeningStatus.CLOSED},
        OpeningStatus.FILLED: {OpeningStatus.OPEN, OpeningStatus.CLOSED},
        OpeningStatus.CLOSED: {OpeningStatus.OPEN},
    }
    current = OpeningStatus(opening.status)
    target = OpeningStatus(body.status)
    if target not in allowed.get(current, set()):
        raise HTTPException(
            409,
            f"An opening that is {current.value.lower().replace('_', ' ')} "
            f"can’t move to {target.value.lower().replace('_', ' ')}",
        )
    opening.status = target
    opening.closed_at = _now() if target == OpeningStatus.CLOSED else None
    opening.close_reason = (
        None if target == OpeningStatus.OPEN else (body.reason or "").strip() or None
    )
    opening.version += 1
    opening.updated_at = _now()
    session.add(opening)
    await svc.event(
        session,
        tenant_id,
        opening.id,
        principal.user_account_id,
        "STATUS_CHANGED",
        {"from": current.value, "to": target.value, "reason": body.reason},
    )
    await session.flush()
    return await _detail(session, tenant_id, acc, principal, opening.id)


@router.get("/openings/{opening_id}/events", response_model=list[EventResponse])
async def opening_events(
    opening_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[dict]:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id)
    acc.require_view(opening)
    return await svc.events_public(
        session, tenant_id, "AND ev.opening_id = :oid", {"oid": opening.id}
    )


async def _sync_filled(session, tenant_id, opening: JobOpening, actor) -> None:
    """FILLED tracks the hire count: reached → FILLED, dropped below → OPEN again."""
    hired = await svc.hired_count(session, tenant_id, opening.id)
    if opening.status == OpeningStatus.OPEN and hired >= opening.positions:
        opening.status = OpeningStatus.FILLED
        await svc.event(
            session,
            tenant_id,
            opening.id,
            actor,
            "STATUS_CHANGED",
            {"from": "OPEN", "to": "FILLED", "reason": "All positions filled"},
        )
    elif opening.status == OpeningStatus.FILLED and hired < opening.positions:
        opening.status = OpeningStatus.OPEN
        await svc.event(
            session,
            tenant_id,
            opening.id,
            actor,
            "STATUS_CHANGED",
            {"from": "FILLED", "to": "OPEN", "reason": "Positions available again"},
        )
    else:
        return
    opening.version += 1
    opening.updated_at = _now()
    session.add(opening)


# ─── Applications ───────────────────────────────────────────────────────────


def _show_pay(acc: Access) -> bool:
    return acc.read is not None or acc.manage is not None


async def _stage_map(session, tenant_id) -> dict[UUID, RecruitmentStage]:
    return {s.id: s for s in await svc.ensure_stages(session, tenant_id)}


@router.get("/openings/{opening_id}/applications", response_model=list[ApplicationSummary])
async def list_applications(
    opening_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> list[dict]:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id)
    acc.require_view(opening)
    stages = await _stage_map(session, tenant_id)
    rows = await svc.application_rows(
        session, tenant_id, "AND a.opening_id = :oid", {"oid": opening.id}
    )
    pay = _show_pay(acc) and acc.recruiter_view(opening)
    return [svc.application_public(*r, stages, pay) for r in rows]


def _apply_candidate(candidate: Candidate, body: CandidateInput) -> None:
    for field in (
        "first_name",
        "last_name",
        "email",
        "phone",
        "location",
        "current_company",
        "current_title",
        "total_experience_years",
        "current_ctc",
        "expected_ctc",
        "notice_period_days",
        "source",
        "source_detail",
        "skills",
        "summary",
    ):
        setattr(candidate, field, getattr(body, field))
    candidate.links = [link.model_dump() for link in body.links]


async def _email_owner(session, tenant_id, email: str | None, exclude: UUID | None = None):
    if not email:
        return None
    query = select(Candidate).where(
        Candidate.tenant_id == tenant_id, Candidate.email == email.lower()
    )
    if exclude:
        query = query.where(Candidate.id != exclude)
    return (await session.execute(query)).scalars().first()


@router.post(
    "/openings/{opening_id}/applications", response_model=ApplicationSummary, status_code=201
)
async def add_application(
    opening_id: str,
    body: ApplicationCreate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    opening = await svc.get_opening(session, tenant_id, opening_id, lock=True)
    acc.require_manage(opening)
    if opening.status != OpeningStatus.OPEN:
        raise HTTPException(409, "Candidates can only be added while the opening is open")
    stages = await _stage_map(session, tenant_id)
    matched = False
    if body.candidate_id:
        candidate = await svc.get_candidate(session, tenant_id, body.candidate_id)
        await _require_candidate_access(session, tenant_id, acc, candidate, manage=True)
    else:
        assert body.candidate is not None
        await svc.lock_resource(session, tenant_id, "candidate-email")
        candidate = await _email_owner(session, tenant_id, body.candidate.email)
        if candidate is not None:
            matched = True
        else:
            candidate = Candidate(
                tenant_id=tenant_id,
                id=uuid4(),
                first_name="",
                last_name="",
                source="OTHER",
                created_by=principal.user_account_id,
            )
            _apply_candidate(candidate, body.candidate)
            session.add(candidate)
            await session.flush()
    duplicate = (
        await session.execute(
            select(JobApplication.id).where(
                JobApplication.tenant_id == tenant_id,
                JobApplication.opening_id == opening.id,
                JobApplication.candidate_id == candidate.id,
            )
        )
    ).first()
    if duplicate:
        raise HTTPException(
            409,
            f"{candidate.first_name} {candidate.last_name} is already in this opening’s pipeline",
        )
    stage_uid = svc.parse_id(body.stage_id, "stage")
    if stage_uid is not None:
        stage = stages.get(stage_uid)
        if stage is None or not stage.is_active or stage.category != StageCategory.ACTIVE:
            raise HTTPException(422, "Pick an active in-progress stage to start in")
    else:
        stage = svc.entry_stage(list(stages.values()))
    now = _now()
    application = JobApplication(
        tenant_id=tenant_id,
        id=uuid4(),
        opening_id=opening.id,
        candidate_id=candidate.id,
        stage_id=stage.id,
        owner_user_id=principal.user_account_id,
        applied_at=now,
        stage_changed_at=now,
        created_by=principal.user_account_id,
    )
    session.add(application)
    await session.flush()
    await svc.event(
        session,
        tenant_id,
        opening.id,
        principal.user_account_id,
        "APPLICATION_ADDED",
        {"stage": stage.name, "matched_existing": matched},
        application.id,
    )
    if body.note:
        await svc.event(
            session,
            tenant_id,
            opening.id,
            principal.user_account_id,
            "NOTE",
            {"body": body.note.strip()},
            application.id,
        )
    await session.flush()
    result = svc.application_public(
        application, candidate, opening, 1 if body.note else 0, stages, _show_pay(acc)
    )
    result["matched_existing"] = matched
    return result


async def _load_application(session, tenant_id, acc: Access, application_id: str, lock=False):
    application = await svc.get_application(session, tenant_id, application_id, lock=lock)
    opening = await svc.get_opening(
        session, tenant_id, to_typed_id("job_opening", application.opening_id), lock=lock
    )
    acc.require_view(opening)
    return application, opening


async def _application_detail(session, tenant_id, acc: Access, application, opening) -> dict:
    stages = await _stage_map(session, tenant_id)
    candidate = await svc.get_candidate(session, tenant_id, application.candidate_id)
    notes = (
        await session.execute(
            text("""SELECT count(*) FROM recruitment_events
                    WHERE tenant_id = :tid AND application_id = :aid AND action = 'NOTE'"""),
            {"tid": tenant_id, "aid": application.id},
        )
    ).scalar() or 0
    pay = _show_pay(acc) and acc.recruiter_view(opening)
    base = svc.application_public(application, candidate, opening, notes, stages, pay)
    events = await svc.events_public(
        session, tenant_id, "AND ev.application_id = :aid", {"aid": application.id}
    )
    where, params = acc.opening_filter_sql("o")
    others = await svc.application_rows(
        session,
        tenant_id,
        f"AND a.candidate_id = :cid AND a.id <> :aid {where}",
        {"cid": candidate.id, "aid": application.id, **params},
    )
    stage = stages.get(application.stage_id)
    manages = acc.manages(opening)
    return dict(
        **base,
        events=events,
        other_applications=[
            dict(
                id=to_typed_id("job_application", a.id),
                opening_id=to_typed_id("job_opening", o.id),
                opening_code=o.code,
                opening_title=o.title,
                stage_name=stages[a.stage_id].name if a.stage_id in stages else "",
                stage_category=stages[a.stage_id].category if a.stage_id in stages else "",
            )
            for a, _c, o, _n in others
        ],
        can_manage=manages,
        can_hire=manages
        and stage is not None
        and stage.category == StageCategory.HIRED
        and application.hired_employment_id is None,
        hire_defaults=dict(
            first_name=candidate.first_name,
            last_name=candidate.last_name,
            legal_entity_id=to_typed_id("legal_entity", opening.legal_entity_id),
            org_unit_id=to_typed_id("org_unit", opening.org_unit_id),
            job_id=svc.typed("job", opening.job_id),
            location_id=svc.typed("location", opening.location_id),
            manager_employment_id=svc.typed("employment", opening.hiring_manager_employment_id),
            hire_date=opening.target_start_date,
        )
        if manages
        else None,
    )


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
async def get_application(
    application_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    application, opening = await _load_application(session, tenant_id, acc, application_id)
    return await _application_detail(session, tenant_id, acc, application, opening)


@router.post("/applications/{application_id}/move", response_model=ApplicationDetail)
async def move_application(
    application_id: str,
    body: ApplicationMove,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    application, opening = await _load_application(
        session, tenant_id, acc, application_id, lock=True
    )
    acc.require_manage(opening)
    if opening.status not in LIVE:
        raise HTTPException(409, "Reopen the opening before moving candidates")
    if body.expected_version is not None and body.expected_version != application.version:
        raise HTTPException(409, "Someone else moved this candidate — reload and try again")
    stages = await _stage_map(session, tenant_id)
    target = stages.get(svc.parse_id(body.stage_id, "stage"))
    if target is None or not target.is_active:
        raise HTTPException(422, "Pick an active stage")
    current = stages.get(application.stage_id)
    if target.id == application.stage_id:
        return await _application_detail(session, tenant_id, acc, application, opening)
    if application.hired_employment_id is not None:
        raise HTTPException(409, "This candidate is already an employee; their stage is final")
    reason = (body.reason or "").strip() or None
    if target.category in (StageCategory.REJECTED, StageCategory.WITHDRAWN) and not reason:
        raise HTTPException(422, "Give a reason")
    if target.category == StageCategory.HIRED and opening.status == OpeningStatus.FILLED:
        raise HTTPException(409, "Every position is filled — increase positions or reopen first")
    application.stage_id = target.id
    application.stage_changed_at = _now()
    application.outcome_reason = (
        reason if target.category in (StageCategory.REJECTED, StageCategory.WITHDRAWN) else None
    )
    application.version += 1
    application.updated_at = _now()
    session.add(application)
    await svc.event(
        session,
        tenant_id,
        opening.id,
        principal.user_account_id,
        "STAGE_CHANGED",
        {
            "from": current.name if current else None,
            "to": target.name,
            "category": target.category,
            "reason": reason,
        },
        application.id,
    )
    await session.flush()
    await _sync_filled(session, tenant_id, opening, principal.user_account_id)
    await session.flush()
    return await _application_detail(session, tenant_id, acc, application, opening)


@router.patch("/applications/{application_id}", response_model=ApplicationDetail)
async def update_application(
    application_id: str,
    body: ApplicationUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    application, opening = await _load_application(
        session, tenant_id, acc, application_id, lock=True
    )
    acc.require_manage(opening)
    rating = None if body.clear_rating else body.rating
    if rating != application.rating:
        application.rating = rating
        application.version += 1
        application.updated_at = _now()
        session.add(application)
        await svc.event(
            session,
            tenant_id,
            opening.id,
            principal.user_account_id,
            "RATED",
            {"rating": rating},
            application.id,
        )
        await session.flush()
    return await _application_detail(session, tenant_id, acc, application, opening)


@router.post("/applications/{application_id}/notes", response_model=ApplicationDetail)
async def add_note(
    application_id: str,
    body: NoteCreate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    """Recruiters and the opening's stakeholders (hiring manager, requester) leave feedback."""
    acc = await _access(session, tenant_id, principal, scope)
    application, opening = await _load_application(session, tenant_id, acc, application_id)
    await svc.event(
        session,
        tenant_id,
        opening.id,
        principal.user_account_id,
        "NOTE",
        {"body": body.body},
        application.id,
    )
    await session.flush()
    return await _application_detail(session, tenant_id, acc, application, opening)


@router.post("/applications/{application_id}/hire", response_model=ApplicationDetail)
async def link_hire(
    application_id: str,
    body: ApplicationHire,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    """Record the employee created for a hired candidate (Employees → Add employee)."""
    acc = await _access(session, tenant_id, principal, scope)
    application, opening = await _load_application(
        session, tenant_id, acc, application_id, lock=True
    )
    acc.require_manage(opening)
    stages = await _stage_map(session, tenant_id)
    stage = stages.get(application.stage_id)
    if stage is None or stage.category != StageCategory.HIRED:
        raise HTTPException(409, "Move the candidate to a hired stage first")
    if application.hired_employment_id is not None:
        raise HTTPException(409, "This candidate is already linked to an employee")
    employment_id = svc.parse_id(body.employment_id, "employee")
    row = (
        await session.execute(
            text("SELECT legal_entity_id FROM employments WHERE tenant_id = :tid AND id = :id"),
            {"tid": tenant_id, "id": employment_id},
        )
    ).first()
    if row is None:
        raise HTTPException(422, "That employee doesn’t exist")
    if not scope.has("people.write") or not scope.for_permission("people.write").covers_entity(
        row[0]
    ):
        raise HTTPException(403, "You can’t link employees of that company")
    taken = (
        await session.execute(
            select(JobApplication.id).where(
                JobApplication.tenant_id == tenant_id,
                JobApplication.hired_employment_id == employment_id,
            )
        )
    ).first()
    if taken:
        raise HTTPException(409, "That employee is already linked to another candidate")
    application.hired_employment_id = employment_id
    application.version += 1
    application.updated_at = _now()
    session.add(application)
    await svc.event(
        session,
        tenant_id,
        opening.id,
        principal.user_account_id,
        "HIRED",
        {"employment_id": to_typed_id("employment", employment_id)},
        application.id,
    )
    await session.flush()
    return await _application_detail(session, tenant_id, acc, application, opening)


# ─── Talent pool ────────────────────────────────────────────────────────────


def _candidate_filter(acc: Access) -> tuple[str, dict] | None:
    """SQL limiting candidates c to those a recruiter may see; None = not a recruiter."""
    rec = acc.recruiter_filter_sql("o")
    if rec is None:
        return None
    clause, params = rec
    if clause == "":
        return "", {}
    return (
        f"""AND (c.created_by = :cf_uid OR EXISTS (
                SELECT 1 FROM job_applications a
                JOIN job_openings o ON o.tenant_id = a.tenant_id AND o.id = a.opening_id
                WHERE a.tenant_id = c.tenant_id AND a.candidate_id = c.id {clause}))""",
        {"cf_uid": acc.user_id, **params},
    )


async def _require_candidate_access(
    session, tenant_id, acc: Access, candidate: Candidate, manage: bool = False
) -> None:
    """Recruiters see their talent pool; stakeholders see candidates in their openings."""
    if manage and acc.manage is None:
        raise HTTPException(403, "Only recruiters can change candidates")
    rec = _candidate_filter(acc)
    if rec is not None:
        clause, params = rec
        found = (
            await session.execute(
                text(
                    f"SELECT 1 FROM candidates c WHERE c.tenant_id = :tid AND c.id = :cid {clause}"
                ),
                {"tid": tenant_id, "cid": candidate.id, **params},
            )
        ).first()
        if found:
            return
    if not manage:
        where, params = acc.opening_filter_sql("o")
        found = (
            await session.execute(
                text(f"""SELECT 1 FROM job_applications a
                         JOIN job_openings o ON o.tenant_id = a.tenant_id AND o.id = a.opening_id
                         WHERE a.tenant_id = :tid AND a.candidate_id = :cid {where} LIMIT 1"""),
                {"tid": tenant_id, "cid": candidate.id, **params},
            )
        ).first()
        if found:
            return
    raise HTTPException(404, "Candidate not found")


@router.get("/candidates")
async def list_candidates(
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    rec = _candidate_filter(acc)
    if rec is None:
        raise HTTPException(403, "Only recruiters can browse the talent pool")
    where, params = rec
    if q and q.strip():
        where += """ AND (c.first_name || ' ' || c.last_name ILIKE :q OR c.email ILIKE :q
                    OR c.phone ILIKE :q OR c.current_company ILIKE :q OR c.current_title ILIKE :q
                    OR c.skills::text ILIKE :q)"""
        params["q"] = f"%{q.strip()}%"
    base = f"FROM candidates c WHERE c.tenant_id = :tid {where}"
    total = (
        await session.execute(text(f"SELECT count(*) {base}"), {"tid": tenant_id, **params})
    ).scalar() or 0
    ids = [
        r[0]
        for r in await session.execute(
            text(f"SELECT c.id {base} ORDER BY c.updated_at DESC LIMIT :lim OFFSET :off"),
            {"tid": tenant_id, "lim": limit, "off": offset, **params},
        )
    ]
    candidates = (
        {
            c.id: c
            for c in (
                await session.execute(
                    select(Candidate).where(
                        Candidate.tenant_id == tenant_id, col(Candidate.id).in_(ids)
                    )
                )
            ).scalars()
        }
        if ids
        else {}
    )
    stages = await _stage_map(session, tenant_id)
    owhere, oparams = acc.opening_filter_sql("o")
    apps = (
        await svc.application_rows(
            session,
            tenant_id,
            f"AND a.candidate_id = ANY(:cids) {owhere}",
            {"cids": ids, **oparams},
        )
        if ids
        else []
    )
    by_candidate: dict[UUID, list] = {}
    for a, _c, o, _n in apps:
        stage = stages.get(a.stage_id)
        by_candidate.setdefault(a.candidate_id, []).append(
            dict(
                id=to_typed_id("job_application", a.id),
                opening_id=to_typed_id("job_opening", o.id),
                opening_code=o.code,
                opening_title=o.title,
                stage_name=stage.name if stage else "",
                stage_category=stage.category if stage else "",
                stage_color=stage.color if stage else "neutral",
            )
        )
    pay = _show_pay(acc)
    return dict(
        total=total,
        items=[
            dict(
                candidate=svc.candidate_public(candidates[i], pay),
                applications=by_candidate.get(i, []),
            )
            for i in ids
            if i in candidates
        ],
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    candidate = await svc.get_candidate(session, tenant_id, candidate_id)
    await _require_candidate_access(session, tenant_id, acc, candidate)
    return svc.candidate_public(candidate, _show_pay(acc))


class _CandidateUpdate(CandidateInput):
    version: int


@router.put("/candidates/{candidate_id}", response_model=CandidateResponse)
async def update_candidate(
    candidate_id: str,
    body: _CandidateUpdate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    candidate = await svc.get_candidate(session, tenant_id, candidate_id, lock=True)
    await _require_candidate_access(session, tenant_id, acc, candidate, manage=True)
    if body.version != candidate.version:
        raise HTTPException(409, "Someone else changed this candidate — reload and try again")
    await svc.lock_resource(session, tenant_id, "candidate-email")
    if await _email_owner(session, tenant_id, body.email, exclude=candidate.id):
        raise HTTPException(409, "Another candidate already uses that email address")
    _apply_candidate(candidate, body)
    candidate.version += 1
    candidate.updated_at = _now()
    session.add(candidate)
    await _candidate_event(
        session, tenant_id, candidate.id, principal.user_account_id, "CANDIDATE_UPDATED"
    )
    await session.flush()
    return svc.candidate_public(candidate, _show_pay(acc))


async def _candidate_event(session, tenant_id, candidate_id, actor, action, details=None):
    """Write the event into every application's history, so each opening sees it."""
    rows = await session.execute(
        select(JobApplication.id, JobApplication.opening_id).where(
            JobApplication.tenant_id == tenant_id, JobApplication.candidate_id == candidate_id
        )
    )
    for application_id, opening_id in rows:
        await svc.event(session, tenant_id, opening_id, actor, action, details, application_id)


@router.delete("/candidates/{candidate_id}", status_code=204)
async def delete_candidate(
    candidate_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> None:
    """Erase a candidate (e.g. on request), with their applications and resume."""
    acc = await _access(session, tenant_id, principal, scope)
    candidate = await svc.get_candidate(session, tenant_id, candidate_id, lock=True)
    await _require_candidate_access(session, tenant_id, acc, candidate, manage=True)
    hired = (
        await session.execute(
            select(JobApplication.id).where(
                JobApplication.tenant_id == tenant_id,
                JobApplication.candidate_id == candidate.id,
                col(JobApplication.hired_employment_id).is_not(None),
            )
        )
    ).first()
    if hired:
        raise HTTPException(409, "This candidate became an employee and can’t be deleted")
    # Every opening the candidate is in must be one this recruiter manages.
    openings = (
        await session.execute(
            select(JobOpening)
            .join(
                JobApplication,
                (JobApplication.tenant_id == JobOpening.tenant_id)
                & (JobApplication.opening_id == JobOpening.id),
            )
            .where(JobOpening.tenant_id == tenant_id, JobApplication.candidate_id == candidate.id)
        )
    ).scalars()
    if any(not acc.manages(o) for o in openings):
        raise HTTPException(403, "This candidate is also in openings you don’t recruit for")
    if candidate.resume_ref:
        session.info.setdefault("delete_files", []).append(candidate.resume_ref)
    await session.delete(candidate)
    await session.flush()


# ─── Resumes ────────────────────────────────────────────────────────────────


@router.post("/candidates/{candidate_id}/resume", response_model=CandidateResponse)
async def upload_resume(
    candidate_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    file: UploadFile = File(...),
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    candidate = await svc.get_candidate(session, tenant_id, candidate_id, lock=True)
    await _require_candidate_access(session, tenant_id, acc, candidate, manage=True)
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "The resume is larger than the upload limit")
    name = svc.clean_filename(file.filename or "resume")
    mime = None
    for magic, (kind, extensions) in RESUME_TYPES.items():
        if content.startswith(magic) and name.lower().endswith(extensions):
            mime = kind
            break
    if mime is None:
        raise HTTPException(415, "Upload the resume as a PDF or Word document")
    ref = await run_in_threadpool(
        document_store.save, f"recruitment/{tenant_id}/{candidate.id}/{uuid4()}_{name}", content
    )
    session.info.setdefault("created_files", []).append(ref)
    if candidate.resume_ref:
        session.info.setdefault("delete_files", []).append(candidate.resume_ref)
    candidate.resume_ref, candidate.resume_file_name = ref, name
    candidate.resume_mime_type, candidate.resume_size = mime, len(content)
    candidate.resume_uploaded_at = now_utc()
    candidate.version += 1
    candidate.updated_at = _now()
    session.add(candidate)
    await _candidate_event(
        session,
        tenant_id,
        candidate.id,
        principal.user_account_id,
        "RESUME_UPLOADED",
        {"file_name": name},
    )
    await session.flush()
    return svc.candidate_public(candidate, _show_pay(acc))


@router.delete("/candidates/{candidate_id}/resume", response_model=CandidateResponse)
async def delete_resume(
    candidate_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> dict:
    acc = await _access(session, tenant_id, principal, scope)
    candidate = await svc.get_candidate(session, tenant_id, candidate_id, lock=True)
    await _require_candidate_access(session, tenant_id, acc, candidate, manage=True)
    if candidate.resume_ref:
        session.info.setdefault("delete_files", []).append(candidate.resume_ref)
        candidate.resume_ref = candidate.resume_file_name = candidate.resume_mime_type = None
        candidate.resume_size = candidate.resume_uploaded_at = None
        candidate.version += 1
        candidate.updated_at = _now()
        session.add(candidate)
        await _candidate_event(
            session, tenant_id, candidate.id, principal.user_account_id, "RESUME_REMOVED"
        )
        await session.flush()
    return svc.candidate_public(candidate, _show_pay(acc))


@router.get("/candidates/{candidate_id}/resume")
async def download_resume(
    candidate_id: str,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
    inline: bool = False,
):
    acc = await _access(session, tenant_id, principal, scope)
    candidate = await svc.get_candidate(session, tenant_id, candidate_id)
    await _require_candidate_access(session, tenant_id, acc, candidate)
    if not candidate.resume_ref:
        raise HTTPException(404, "No resume uploaded")
    try:
        content = await run_in_threadpool(document_store.load, candidate.resume_ref)
    except document_store.DocumentMissing:
        raise HTTPException(404, "The resume file is missing from storage") from None
    show_inline = inline and candidate.resume_mime_type == "application/pdf"
    return Response(
        content=content,
        media_type=candidate.resume_mime_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f"{'inline' if show_inline else 'attachment'}; "
                f'filename="{candidate.resume_file_name or "resume"}"'
            ),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )

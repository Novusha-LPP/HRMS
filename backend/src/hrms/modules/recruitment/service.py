"""Queries and building blocks shared by the recruitment endpoints."""

import re
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.datetime_utils import now_utc
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.modules.recruitment.models import (
    Candidate,
    JobApplication,
    JobOpening,
    RecruitmentEvent,
    RecruitmentStage,
    StageCategory,
)

APPROVAL_KIND = "JOB_REQUISITION"

DEFAULT_STAGES = [
    ("Applied", StageCategory.ACTIVE, "neutral"),
    ("Screening", StageCategory.ACTIVE, "info"),
    ("Shortlisted", StageCategory.ACTIVE, "brand"),
    ("Interview", StageCategory.ACTIVE, "plum"),
    ("Selected", StageCategory.ACTIVE, "success"),
    ("Offer released", StageCategory.ACTIVE, "warning"),
    ("Onboarding", StageCategory.HIRED, "success"),
    ("Rejected", StageCategory.REJECTED, "danger"),
    ("Withdrawn", StageCategory.WITHDRAWN, "neutral"),
]


def typed(kind: str, value: UUID | None) -> str | None:
    return to_typed_id(kind, value) if value else None


def parse_id(value: str | None, field: str = "id") -> UUID | None:
    if not value:
        return None
    try:
        return to_uuid(value)
    except HTTPException:
        raise HTTPException(422, f"Invalid {field.replace('_', ' ')}") from None


def clean_filename(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name)[:100] or "resume"


# ─── Stages ─────────────────────────────────────────────────────────────────


async def ensure_stages(session, tenant_id: UUID) -> list[RecruitmentStage]:
    """The tenant's pipeline, seeding the default one on first use."""
    stages = await list_stages(session, tenant_id)
    if stages:
        return stages
    await lock_resource(session, tenant_id, "recruitment-stages")
    stages = await list_stages(session, tenant_id)
    if stages:
        return stages
    for i, (name, category, color) in enumerate(DEFAULT_STAGES):
        session.add(
            RecruitmentStage(
                tenant_id=tenant_id,
                id=uuid4(),
                name=name,
                category=category,
                color=color,
                sequence=i,
            )
        )
    await session.flush()
    return await list_stages(session, tenant_id)


async def list_stages(session, tenant_id: UUID) -> list[RecruitmentStage]:
    rows = await session.execute(
        select(RecruitmentStage)
        .where(RecruitmentStage.tenant_id == tenant_id)
        .order_by(col(RecruitmentStage.sequence), col(RecruitmentStage.name))
    )
    return list(rows.scalars())


def entry_stage(stages: list[RecruitmentStage]) -> RecruitmentStage:
    for stage in stages:
        if stage.is_active and stage.category == StageCategory.ACTIVE:
            return stage
    raise HTTPException(409, "The pipeline has no active in-progress stage")


def stage_public(stage: RecruitmentStage) -> dict:
    return dict(
        id=to_typed_id("recruitment_stage", stage.id),
        name=stage.name,
        category=stage.category,
        color=stage.color,
        sequence=stage.sequence,
        is_active=stage.is_active,
        version=stage.version,
    )


# ─── Lookups ────────────────────────────────────────────────────────────────


async def get_opening(session, tenant_id: UUID, opening_id: str, lock=False) -> JobOpening:
    uid = parse_id(opening_id, "opening")
    query = select(JobOpening).where(JobOpening.tenant_id == tenant_id, JobOpening.id == uid)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    opening = (await session.execute(query)).scalars().first()
    if opening is None:
        raise HTTPException(404, "Opening not found")
    return opening


async def get_application(session, tenant_id: UUID, application_id: str, lock=False):
    uid = parse_id(application_id, "application")
    query = select(JobApplication).where(
        JobApplication.tenant_id == tenant_id, JobApplication.id == uid
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    application = (await session.execute(query)).scalars().first()
    if application is None:
        raise HTTPException(404, "Application not found")
    return application


async def get_candidate(session, tenant_id: UUID, candidate_id: UUID | str, lock=False):
    uid = candidate_id if isinstance(candidate_id, UUID) else parse_id(candidate_id, "candidate")
    query = select(Candidate).where(Candidate.tenant_id == tenant_id, Candidate.id == uid)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    candidate = (await session.execute(query)).scalars().first()
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    return candidate


async def next_code(session, tenant_id: UUID) -> str:
    await lock_resource(session, tenant_id, "job-opening-code")
    current = (
        await session.execute(
            text("""
                SELECT COALESCE(MAX(CAST(substring(code FROM 5) AS integer)), 0)
                FROM job_openings WHERE tenant_id = :tid AND code ~ '^REQ-[0-9]{1,9}$'
            """),
            {"tid": tenant_id},
        )
    ).scalar()
    return f"REQ-{int(current or 0) + 1:04d}"


async def user_names(session, tenant_id: UUID, ids) -> dict[UUID, str]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    rows = await session.execute(
        text("""
            SELECT ua.id, COALESCE(p.legal_first_name || ' ' || p.legal_last_name,
                                   ua.email, ua.employee_code, 'Unknown user')
            FROM user_accounts ua
            LEFT JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
            LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            WHERE ua.tenant_id = :tid AND ua.id = ANY(:ids)
        """),
        {"tid": tenant_id, "ids": ids},
    )
    return {r[0]: r[1] for r in rows}


async def unit_entity(session, tenant_id: UUID, org_unit_id: UUID) -> UUID:
    row = (
        await session.execute(
            text("""SELECT legal_entity_id FROM org_units
                    WHERE tenant_id = :tid AND id = :id AND status = 'ACTIVE'
                      AND archived_at IS NULL"""),
            {"tid": tenant_id, "id": org_unit_id},
        )
    ).first()
    if row is None:
        raise HTTPException(422, "That department or team doesn’t exist or is archived")
    if row[0] is None:
        raise HTTPException(422, "That department isn’t attached to a company")
    return row[0]


async def check_reference(
    session,
    tenant_id: UUID,
    table: str,
    uid: UUID | None,
    label: str,
    legal_entity_id: UUID | None = None,
) -> None:
    if uid is None:
        return
    row = (
        await session.execute(
            text(f"SELECT legal_entity_id FROM {table} WHERE tenant_id = :tid AND id = :id")
            if table in ("locations", "employments")
            else text(f"SELECT NULL FROM {table} WHERE tenant_id = :tid AND id = :id"),
            {"tid": tenant_id, "id": uid},
        )
    ).first()
    if row is None:
        raise HTTPException(422, f"That {label} doesn’t exist")
    if (
        table == "locations"
        and row[0] is not None
        and legal_entity_id
        and row[0] != legal_entity_id
    ):
        raise HTTPException(422, "That location belongs to a different company")


# ─── Openings ───────────────────────────────────────────────────────────────

_OPENING_SELECT = """
    SELECT o.*,
           le.name AS legal_entity_name,
           ou.name AS org_unit_name,
           j.title AS job_title,
           l.name AS location_name,
           hp.legal_first_name || ' ' || hp.legal_last_name AS hiring_manager_name,
           COALESCE(rp.legal_first_name || ' ' || rp.legal_last_name, ua.email, ua.employee_code)
               AS requested_by_name
    FROM job_openings o
    LEFT JOIN legal_entities le ON le.tenant_id = o.tenant_id AND le.id = o.legal_entity_id
    LEFT JOIN org_units ou ON ou.tenant_id = o.tenant_id AND ou.id = o.org_unit_id
    LEFT JOIN jobs j ON j.tenant_id = o.tenant_id AND j.id = o.job_id
    LEFT JOIN locations l ON l.tenant_id = o.tenant_id AND l.id = o.location_id
    LEFT JOIN employments he
        ON he.tenant_id = o.tenant_id AND he.id = o.hiring_manager_employment_id
    LEFT JOIN persons hp ON hp.tenant_id = he.tenant_id AND hp.id = he.person_id
    LEFT JOIN user_accounts ua ON ua.tenant_id = o.tenant_id AND ua.id = o.requested_by
    LEFT JOIN employments re ON re.tenant_id = ua.tenant_id AND re.id = ua.employment_id
    LEFT JOIN persons rp ON rp.tenant_id = re.tenant_id AND rp.id = re.person_id
    WHERE o.tenant_id = :tid
"""


async def opening_rows(
    session,
    tenant_id: UUID,
    where: str = "",
    params: dict | None = None,
    order: str = "o.updated_at DESC",
    limit: int = 500,
) -> list:
    rows = await session.execute(
        text(f"{_OPENING_SELECT} {where} ORDER BY {order} LIMIT {int(limit)}"),
        {"tid": tenant_id, **(params or {})},
    )
    return [SimpleNamespace(**dict(r)) for r in rows.mappings()]


async def stage_counts(session, tenant_id: UUID, opening_ids: list[UUID]) -> dict:
    if not opening_ids:
        return {}
    rows = await session.execute(
        text("""SELECT opening_id, stage_id, count(*) FROM job_applications
                WHERE tenant_id = :tid AND opening_id = ANY(:ids) GROUP BY 1, 2"""),
        {"tid": tenant_id, "ids": opening_ids},
    )
    counts: dict[UUID, dict[UUID, int]] = {}
    for opening_id, stage_id, n in rows:
        counts.setdefault(opening_id, {})[stage_id] = n
    return counts


def opening_summary(row, counts: dict[UUID, int], stages: dict[UUID, RecruitmentStage]) -> dict:
    hired = sum(n for s, n in counts.items() if stages.get(s) and stages[s].category == "HIRED")
    active = sum(n for s, n in counts.items() if stages.get(s) and stages[s].category == "ACTIVE")
    return dict(
        id=to_typed_id("job_opening", row.id),
        code=row.code,
        title=row.title,
        status=row.status,
        priority=row.priority,
        employment_type=row.employment_type,
        work_mode=row.work_mode,
        positions=row.positions,
        hired=hired,
        candidates=sum(counts.values()),
        in_progress=active,
        legal_entity_id=to_typed_id("legal_entity", row.legal_entity_id),
        legal_entity_name=row.legal_entity_name,
        org_unit_id=to_typed_id("org_unit", row.org_unit_id),
        org_unit_name=row.org_unit_name,
        job_title=row.job_title,
        location_name=row.location_name,
        hiring_manager_employment_id=typed("employment", row.hiring_manager_employment_id),
        hiring_manager_name=row.hiring_manager_name,
        requested_by_name=row.requested_by_name,
        target_start_date=row.target_start_date,
        created_at=row.created_at,
        updated_at=row.updated_at,
        submitted_at=row.submitted_at,
        stage_counts=[
            dict(stage_id=to_typed_id("recruitment_stage", s), count=n) for s, n in counts.items()
        ],
    )


async def hired_count(session, tenant_id: UUID, opening_id: UUID) -> int:
    return (
        await session.execute(
            text("""SELECT count(*) FROM job_applications a
                    JOIN recruitment_stages s ON s.tenant_id = a.tenant_id AND s.id = a.stage_id
                    WHERE a.tenant_id = :tid AND a.opening_id = :oid AND s.category = 'HIRED'"""),
            {"tid": tenant_id, "oid": opening_id},
        )
    ).scalar() or 0


async def event(
    session,
    tenant_id: UUID,
    opening_id: UUID,
    actor: UUID | None,
    action: str,
    details: dict | None = None,
    application_id: UUID | None = None,
) -> None:
    session.add(
        RecruitmentEvent(
            tenant_id=tenant_id,
            id=uuid4(),
            opening_id=opening_id,
            application_id=application_id,
            actor_user_id=actor,
            action=action,
            details=details or {},
            created_at=now_utc(),
        )
    )


# ─── Candidates & applications ──────────────────────────────────────────────


def candidate_public(c: Candidate, show_pay: bool) -> dict:
    return dict(
        id=to_typed_id("candidate", c.id),
        first_name=c.first_name,
        last_name=c.last_name,
        full_name=f"{c.first_name} {c.last_name}",
        email=c.email,
        phone=c.phone,
        location=c.location,
        current_company=c.current_company,
        current_title=c.current_title,
        total_experience_years=c.total_experience_years,
        current_ctc=c.current_ctc if show_pay else None,
        expected_ctc=c.expected_ctc if show_pay else None,
        notice_period_days=c.notice_period_days,
        source=c.source,
        source_detail=c.source_detail,
        links=c.links or [],
        skills=c.skills or [],
        summary=c.summary,
        resume=dict(
            file_name=c.resume_file_name,
            mime_type=c.resume_mime_type,
            size=c.resume_size or 0,
            uploaded_at=c.resume_uploaded_at,
        )
        if c.resume_ref
        else None,
        created_at=c.created_at,
        updated_at=c.updated_at,
        version=c.version,
    )


async def application_rows(session, tenant_id: UUID, where: str, params: dict) -> list:
    """Applications with their opening, stage and candidate, plus note counts."""
    rows = await session.execute(
        text(f"""
            SELECT a.id
            FROM job_applications a
            JOIN job_openings o ON o.tenant_id = a.tenant_id AND o.id = a.opening_id
            WHERE a.tenant_id = :tid {where}
            ORDER BY a.stage_changed_at DESC
            LIMIT 2000
        """),
        {"tid": tenant_id, **params},
    )
    ids = [r[0] for r in rows]
    if not ids:
        return []
    apps = list(
        (
            await session.execute(
                select(JobApplication).where(
                    JobApplication.tenant_id == tenant_id, col(JobApplication.id).in_(ids)
                )
            )
        ).scalars()
    )
    candidates = {
        c.id: c
        for c in (
            await session.execute(
                select(Candidate).where(
                    Candidate.tenant_id == tenant_id,
                    col(Candidate.id).in_({a.candidate_id for a in apps}),
                )
            )
        ).scalars()
    }
    openings = {
        o.id: o
        for o in (
            await session.execute(
                select(JobOpening).where(
                    JobOpening.tenant_id == tenant_id,
                    col(JobOpening.id).in_({a.opening_id for a in apps}),
                )
            )
        ).scalars()
    }
    notes = dict(
        (
            await session.execute(
                text("""SELECT application_id, count(*) FROM recruitment_events
                        WHERE tenant_id = :tid AND application_id = ANY(:ids) AND action = 'NOTE'
                        GROUP BY 1"""),
                {"tid": tenant_id, "ids": ids},
            )
        ).all()
    )
    order = {uid: i for i, uid in enumerate(ids)}
    apps.sort(key=lambda a: order[a.id])
    return [
        (a, candidates[a.candidate_id], openings[a.opening_id], notes.get(a.id, 0)) for a in apps
    ]


def application_public(app, candidate, opening, notes, stages: dict, show_pay: bool) -> dict:
    stage = stages.get(app.stage_id)
    return dict(
        id=to_typed_id("job_application", app.id),
        opening_id=to_typed_id("job_opening", opening.id),
        opening_code=opening.code,
        opening_title=opening.title,
        opening_status=opening.status,
        candidate=candidate_public(candidate, show_pay),
        stage_id=to_typed_id("recruitment_stage", app.stage_id),
        stage_name=stage.name if stage else "Unknown",
        stage_category=stage.category if stage else "ACTIVE",
        rating=app.rating,
        hired_employment_id=typed("employment", app.hired_employment_id),
        outcome_reason=app.outcome_reason,
        applied_at=app.applied_at,
        stage_changed_at=app.stage_changed_at,
        notes_count=notes,
        version=app.version,
    )


async def events_public(session, tenant_id: UUID, where: str, params: dict) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(f"""
                SELECT ev.*, c.first_name || ' ' || c.last_name AS candidate_name
                FROM recruitment_events ev
                LEFT JOIN job_applications a
                    ON a.tenant_id = ev.tenant_id AND a.id = ev.application_id
                LEFT JOIN candidates c ON c.tenant_id = a.tenant_id AND c.id = a.candidate_id
                WHERE ev.tenant_id = :tid {where}
                ORDER BY ev.created_at DESC
                LIMIT 300
            """),
                {"tid": tenant_id, **params},
            )
        )
        .mappings()
        .all()
    )
    names = await user_names(session, tenant_id, [r["actor_user_id"] for r in rows])
    return [
        dict(
            id=to_typed_id("recruitment_event", r["id"]),
            action=r["action"],
            actor_name=names.get(r["actor_user_id"]) if r["actor_user_id"] else "System",
            application_id=typed("job_application", r["application_id"]),
            candidate_name=r["candidate_name"],
            details=r["details"] or {},
            created_at=r["created_at"],
        )
        for r in rows
    ]

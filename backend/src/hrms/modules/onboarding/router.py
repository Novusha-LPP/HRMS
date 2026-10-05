"""
Onboarding module.

Templates:   GET/POST /v1/onboarding/templates
Cases:       POST     /v1/onboarding/cases          (start onboarding)
             GET      /v1/onboarding/cases/{id}     (full checklist)
             GET      /v1/onboarding/cases          (list — filter by employment)
Items:       PATCH    /v1/onboarding/items/{id}     (update status / upload doc)
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import (
    ScopeDep,
    authorize_employment,
    read_scope,
    require_global_permission,
    require_permission,
    visible_employment_ids,
)
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.modules.onboarding.models import (
    CaseStatus,
    ItemStatus,
    OnboardingCase,
    OnboardingItem,
    OnboardingTemplate,
    OnboardingTemplateItem,
)
from hrms.modules.onboarding.schemas import (
    CaseCreateRequest,
    CaseResponse,
    ItemUpdateRequest,
    OnboardingItemResponse,
    TemplateCreate,
    TemplateItemResponse,
    TemplateResponse,
)

router = APIRouter(prefix="/v1/onboarding", tags=["Onboarding"])

# Default template items seeded when no template exists
_DEFAULT_ITEMS = [
    ("Welcome & Orientation", "TASK", "HR", 1, True, 0),
    ("Sign Employment Contract", "DOCUMENT", "EMPLOYEE", 1, True, 1),
    ("Submit Identity Documents (Aadhaar, PAN)", "DOCUMENT", "EMPLOYEE", 3, True, 2),
    ("Submit Bank Account Details", "DOCUMENT", "EMPLOYEE", 3, True, 3),
    ("Complete Emergency Contact Form", "FORM", "EMPLOYEE", 5, True, 4),
    ("IT Account Setup", "IT_SETUP", "IT", 2, True, 5),
    ("Read and Acknowledge HR Policy", "POLICY_ACK", "EMPLOYEE", 7, True, 6),
    ("Read and Acknowledge Code of Conduct", "POLICY_ACK", "EMPLOYEE", 7, True, 7),
    ("Asset Issuance (Laptop, ID Card)", "TASK", "HR", 3, False, 8),
    ("Complete Induction Training", "TRAINING", "EMPLOYEE", 14, True, 9),
]


# ─── Templates ────────────────────────────────────────────────────────────────


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(tenant_id: TenantDep, session: SessionDep) -> list[TemplateResponse]:
    rows = await session.execute(
        select(OnboardingTemplate)
        .where(OnboardingTemplate.tenant_id == tenant_id)
        .where(OnboardingTemplate.status == "ACTIVE")
    )
    result = []
    for t in rows.scalars():
        items = await _get_template_items(session, tenant_id, t.id)
        result.append(_template_response(t, items))
    return result


@router.post(
    "/templates",
    response_model=TemplateResponse,
    status_code=201,
    dependencies=[require_global_permission("onboarding.write")],
)
async def create_template(
    body: TemplateCreate, tenant_id: TenantDep, session: SessionDep
) -> TemplateResponse:
    tid = uuid4()
    tmpl = OnboardingTemplate(
        tenant_id=tenant_id,
        id=tid,
        name=body.name,
        description=body.description,
        trigger=body.trigger,
        is_default=body.is_default,
    )
    session.add(tmpl)
    items = []
    for i, item in enumerate(body.items):
        iid = uuid4()
        ti = OnboardingTemplateItem(
            tenant_id=tenant_id,
            id=iid,
            template_id=tid,
            title=item.title,
            description=item.description,
            item_type=item.item_type,
            assignee_type=item.assignee_type,
            due_days_from_hire=item.due_days_from_hire,
            required=item.required,
            sequence=item.sequence or i,
        )
        session.add(ti)
        items.append(ti)
    await session.flush()
    return _template_response(tmpl, items)


# ─── Cases ────────────────────────────────────────────────────────────────────


@router.post(
    "/cases",
    response_model=CaseResponse,
    status_code=201,
    summary="Start an onboarding case for a new hire",
    dependencies=[require_permission("onboarding.write")],
)
async def create_case(
    body: CaseCreateRequest,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> CaseResponse:
    scope = scope.for_permission("onboarding.write")
    emp_uuid = to_uuid(body.employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    # Resolve template
    tmpl_uuid: UUID | None = to_uuid(body.template_id) if body.template_id else None
    if tmpl_uuid is None:
        tmpl_uuid = await _get_or_seed_default_template(session, tenant_id)

    # Create case
    case_id = uuid4()
    case = OnboardingCase(
        tenant_id=tenant_id,
        id=case_id,
        employment_id=emp_uuid,
        template_id=tmpl_uuid,
        hire_date=body.hire_date,
    )
    session.add(case)

    # Instantiate items from template
    tmpl_items = await _get_template_items(session, tenant_id, tmpl_uuid)
    items = []
    for ti in tmpl_items:
        iid = uuid4()
        due = body.hire_date + timedelta(days=ti.due_days_from_hire)
        oi = OnboardingItem(
            tenant_id=tenant_id,
            id=iid,
            case_id=case_id,
            template_item_id=ti.id,
            title=ti.title,
            description=ti.description,
            item_type=ti.item_type,
            assignee_type=ti.assignee_type,
            due_date=due,
            required=ti.required,
            sequence=ti.sequence,
        )
        session.add(oi)
        items.append(oi)
    await session.flush()
    return _case_response(case, items)


@router.get("/cases", response_model=list[CaseResponse])
async def list_cases(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    employment_id: str | None = Query(default=None),
) -> list[CaseResponse]:
    scope = read_scope(scope, "onboarding.read")
    q = select(OnboardingCase).where(OnboardingCase.tenant_id == tenant_id)
    if employment_id:
        emp_uuid = to_uuid(employment_id)
        await authorize_employment(session, tenant_id, scope, emp_uuid)
        q = q.where(OnboardingCase.employment_id == emp_uuid)
    elif not scope.is_all:
        allowed_ids = await visible_employment_ids(session, tenant_id, scope)
        q = q.where(col(OnboardingCase.employment_id).in_(allowed_ids))
    rows = await session.execute(q.order_by(OnboardingCase.started_at.desc()))  # type: ignore
    result = []
    for c in rows.scalars():
        items = await _get_case_items(session, tenant_id, c.id)
        result.append(_case_response(c, items))
    return result


@router.get("/cases/{case_id}", response_model=CaseResponse)
async def get_case(
    case_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> CaseResponse:
    scope = read_scope(scope, "onboarding.read")
    c_uuid = to_uuid(case_id)
    row = await session.execute(
        select(OnboardingCase)
        .where(OnboardingCase.tenant_id == tenant_id)
        .where(OnboardingCase.id == c_uuid)
    )
    case = row.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Onboarding case not found")
    await authorize_employment(session, tenant_id, scope, case.employment_id)
    items = await _get_case_items(session, tenant_id, case.id)
    return _case_response(case, items)


# ─── Items ────────────────────────────────────────────────────────────────────


@router.patch(
    "/items/{item_id}",
    response_model=OnboardingItemResponse,
    summary="Update checklist item status",
)
async def update_item(
    item_id: str,
    body: ItemUpdateRequest,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> OnboardingItemResponse:
    i_uuid = to_uuid(item_id)
    row = await session.execute(
        select(OnboardingItem)
        .where(OnboardingItem.tenant_id == tenant_id)
        .where(OnboardingItem.id == i_uuid)
    )
    item = row.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    await lock_resource(session, tenant_id, f"onboarding:{item.case_id}")
    case_row = await session.execute(
        select(OnboardingCase)
        .where(OnboardingCase.tenant_id == tenant_id)
        .where(OnboardingCase.id == item.case_id)
    )
    case = case_row.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Onboarding case not found")
    await authorize_employment(session, tenant_id, scope, case.employment_id)

    if case.status == CaseStatus.CANCELLED:
        raise HTTPException(409, "Cannot update a cancelled onboarding case")
    if item.assignee_type == "EMPLOYEE" and principal.employment_id == case.employment_id:
        scope.require("self.write")
    elif (
        item.assignee_type == "MANAGER"
        and principal.employment_id != case.employment_id
        and scope.has("dashboard.manager")
    ):
        await authorize_employment(
            session, tenant_id, scope.for_permission("dashboard.manager"), case.employment_id
        )
    else:
        await authorize_employment(
            session, tenant_id, scope.for_permission("onboarding.write"), case.employment_id
        )
    if body.status == ItemStatus.SKIPPED and item.required:
        scope.require("onboarding.write")
    item.status = body.status
    if body.notes:
        item.notes = body.notes
    if body.document_key:
        item.document_key = body.document_key
    if body.status == ItemStatus.COMPLETED:
        item.completed_at = datetime.now(UTC)

    if body.status != ItemStatus.COMPLETED:
        item.completed_at = None
    session.add(item)
    await session.flush()

    # Check if all required items in the case are done → auto-complete case
    await _maybe_complete_case(session, tenant_id, item.case_id)
    await session.flush()

    return OnboardingItemResponse(
        id=to_typed_id("onboarding_item", item.id),
        title=item.title,
        description=item.description,
        item_type=item.item_type,
        assignee_type=item.assignee_type,
        due_date=item.due_date,
        required=item.required,
        sequence=item.sequence,
        status=item.status,
        completed_at=item.completed_at,
        notes=item.notes,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _get_template_items(session, tenant_id: UUID, template_id: UUID):
    rows = await session.execute(
        select(OnboardingTemplateItem)
        .where(OnboardingTemplateItem.tenant_id == tenant_id)
        .where(OnboardingTemplateItem.template_id == template_id)
        .order_by(OnboardingTemplateItem.sequence)  # type: ignore
    )
    return list(rows.scalars())


async def _get_case_items(session, tenant_id: UUID, case_id: UUID):
    rows = await session.execute(
        select(OnboardingItem)
        .where(OnboardingItem.tenant_id == tenant_id)
        .where(OnboardingItem.case_id == case_id)
        .order_by(OnboardingItem.sequence)  # type: ignore
    )
    return list(rows.scalars())


async def _get_or_seed_default_template(session, tenant_id: UUID) -> UUID:
    row = await session.execute(
        select(OnboardingTemplate)
        .where(OnboardingTemplate.tenant_id == tenant_id)
        .where(OnboardingTemplate.is_default == True)  # noqa: E712
        .where(OnboardingTemplate.status == "ACTIVE")
    )
    tmpl = row.scalars().first()
    if tmpl:
        return tmpl.id

    # Seed the default template
    tid = uuid4()
    tmpl = OnboardingTemplate(
        tenant_id=tenant_id,
        id=tid,
        name="Standard Employee Onboarding",
        description="Default onboarding checklist for new hires",
        is_default=True,
    )
    session.add(tmpl)
    for title, itype, atype, days, req, seq in _DEFAULT_ITEMS:
        session.add(
            OnboardingTemplateItem(
                tenant_id=tenant_id,
                id=uuid4(),
                template_id=tid,
                title=title,
                item_type=itype,
                assignee_type=atype,
                due_days_from_hire=days,
                required=req,
                sequence=seq,
            )
        )
    # No autoflush (core/database.py), so without this the caller's very next
    # SELECT for these items wouldn't see them until a later request.
    await session.flush()
    return tid


async def _maybe_complete_case(session, tenant_id: UUID, case_id: UUID) -> None:
    items = await _get_case_items(session, tenant_id, case_id)
    all_required_done = all(
        i.status in (ItemStatus.COMPLETED, ItemStatus.SKIPPED) for i in items if i.required
    )
    if all_required_done:
        row = await session.execute(
            select(OnboardingCase)
            .where(OnboardingCase.tenant_id == tenant_id)
            .where(OnboardingCase.id == case_id)
        )
        case = row.scalars().first()
        if case and case.status == CaseStatus.IN_PROGRESS:
            case.status = CaseStatus.COMPLETED
            case.completed_at = datetime.now(UTC)
            session.add(case)
    else:
        case = (
            (
                await session.execute(
                    select(OnboardingCase)
                    .where(OnboardingCase.tenant_id == tenant_id)
                    .where(OnboardingCase.id == case_id)
                )
            )
            .scalars()
            .first()
        )
        if case and case.status == CaseStatus.COMPLETED:
            case.status = CaseStatus.IN_PROGRESS
            case.completed_at = None
            session.add(case)


def _template_response(tmpl: OnboardingTemplate, items: list) -> TemplateResponse:
    return TemplateResponse(
        id=to_typed_id("onboarding_template", tmpl.id),
        name=tmpl.name,
        description=tmpl.description,
        trigger=tmpl.trigger,
        is_default=tmpl.is_default,
        status=tmpl.status,
        items=[
            TemplateItemResponse(
                id=to_typed_id("onboarding_template_item", i.id),
                title=i.title,
                description=i.description,
                item_type=i.item_type,
                assignee_type=i.assignee_type,
                due_days_from_hire=i.due_days_from_hire,
                required=i.required,
                sequence=i.sequence,
            )
            for i in items
        ],
    )


def _case_response(case: OnboardingCase, items: list) -> CaseResponse:
    from hrms.modules.onboarding.models import ItemStatus as IS

    total = len(items)
    completed = sum(1 for i in items if i.status == IS.COMPLETED)
    today = business_today()
    overdue = sum(
        1
        for i in items
        if i.status not in (IS.COMPLETED, IS.SKIPPED) and i.due_date and i.due_date < today
    )
    return CaseResponse(
        id=to_typed_id("onboarding_case", case.id),
        employment_id=to_typed_id("employment", case.employment_id),
        template_id=to_typed_id("onboarding_template", case.template_id),
        status=case.status,
        hire_date=case.hire_date,
        started_at=case.started_at,
        completed_at=case.completed_at,
        total_items=total,
        completed_items=completed,
        overdue_items=overdue,
        items=[
            OnboardingItemResponse(
                id=to_typed_id("onboarding_item", i.id),
                title=i.title,
                description=i.description,
                item_type=i.item_type,
                assignee_type=i.assignee_type,
                due_date=i.due_date,
                required=i.required,
                sequence=i.sequence,
                status=i.status,
                completed_at=i.completed_at,
                notes=i.notes,
            )
            for i in items
        ],
    )

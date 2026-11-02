"""
Payslip templates — /v1/payroll/payslip-templates. What a payslip shows and in which layout.

GET  ""                         the group template, each company's own (or none), the fields
PUT  /group                     save the group template (group-level access)
PUT|DELETE /companies/{id}      a company's own template; DELETE = use the group's again
POST /preview                   a SAMPLE payslip PDF for an unsaved template

Access: payroll.write (Payroll admin) or org.write (HR, Admin), scoped to the companies
concerned. The preview prints made-up figures, so designing a payslip shows nobody's pay.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import col, select
from starlette.concurrency import run_in_threadpool

from hrms.core.authn import CurrentUser
from hrms.core.authz import Scope, ScopeDep, merge_scopes
from hrms.core.config import settings
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today, now_utc, to_tz
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.core.versioning import require_version
from hrms.modules.branding.models import DocumentSignatory
from hrms.modules.branding.router import get_company
from hrms.modules.org.models import LegalEntity
from hrms.modules.payroll.models import PayslipTemplate
from hrms.modules.payroll.payslip import document, render, sample
from hrms.modules.payroll.payslip.issuer import issuer_for
from hrms.modules.payroll.schemas import (
    CompanyPayslipTemplate,
    EmployeeFieldOption,
    PayslipPreviewRequest,
    PayslipTemplateInput,
    PayslipTemplateOverview,
    PayslipTemplateResponse,
    PayslipTemplateSave,
)

router = APIRouter(prefix="/v1/payroll/payslip-templates", tags=["Payroll"])

TEMPLATE_PERMISSIONS = ("payroll.write", "org.write")


async def _template_scope(scope: ScopeDep) -> Scope:
    """The companies the caller may design payslips for, through either permission."""
    held = [p for p in TEMPLATE_PERMISSIONS if scope.has(p)]
    if not held:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Missing permission: payroll.write or org.write"
        )
    return merge_scopes([scope.for_permission(p) for p in held], scope.own_employment_id)


TemplateScope = Annotated[Scope, Depends(_template_scope)]


def settings_of(template: PayslipTemplate | PayslipTemplateInput | None):
    """The renderer's settings for a saved or unsaved template (None: the built-in default)."""
    if template is None:
        return document.TemplateSettings()
    return document.TemplateSettings(
        layout=template.layout,
        title=template.title,
        employee_fields=tuple(template.employee_fields),
        show_attendance=template.show_attendance,
        show_leave_balances=template.show_leave_balances,
        show_employer_contributions=template.show_employer_contributions,
        show_ytd=template.show_ytd,
        hide_zero_lines=template.hide_zero_lines,
        signature_mode=template.signature_mode,
        note_text=template.note_text,
    )


async def templates_for(
    session, tenant_id: UUID, legal_entity_id: UUID | None
) -> tuple[PayslipTemplate | None, PayslipTemplate | None]:
    """The group template and (when legal_entity_id is set) the company's own."""
    ids = [legal_entity_id] if legal_entity_id else []
    rows = await session.execute(
        select(PayslipTemplate)
        .where(PayslipTemplate.tenant_id == tenant_id)
        .where(
            col(PayslipTemplate.legal_entity_id).is_(None)
            | col(PayslipTemplate.legal_entity_id).in_(ids)
        )
    )
    group = company = None
    for row in rows.scalars():
        if row.legal_entity_id is None:
            group = row
        else:
            company = row
    return group, company


async def effective_template(session, tenant_id: UUID, legal_entity_id: UUID | None):
    """The template a company's payslips use: its own, else the group's, else None (default)."""
    group, company = await templates_for(session, tenant_id, legal_entity_id)
    return company or group


def _response(row: PayslipTemplate | None, legal_entity_id: UUID | None = None):
    if row is None:
        return PayslipTemplateResponse(
            id=None,
            legal_entity_id=to_typed_id("legal_entity", legal_entity_id)
            if legal_entity_id
            else None,
            version=None,
            recorded_at=None,
        )
    return PayslipTemplateResponse(
        id=to_typed_id("payslip_template", row.id),
        legal_entity_id=to_typed_id("legal_entity", row.legal_entity_id)
        if row.legal_entity_id
        else None,
        layout=row.layout,
        title=row.title,
        employee_fields=list(row.employee_fields),
        show_attendance=row.show_attendance,
        show_leave_balances=row.show_leave_balances,
        show_employer_contributions=row.show_employer_contributions,
        show_ytd=row.show_ytd,
        hide_zero_lines=row.hide_zero_lines,
        signature_mode=row.signature_mode,
        signatory_id=to_typed_id("document_signatory", row.signatory_id)
        if row.signatory_id
        else None,
        note_text=row.note_text,
        version=row.version,
        recorded_at=row.recorded_at,
    )


async def _signatory_id(
    session, tenant_id: UUID, body: PayslipTemplateInput, legal_entity_id: UUID | None
) -> UUID | None:
    """The chosen signatory, if they may sign for this template's companies (422 otherwise)."""
    if body.signatory_id is None:
        return None
    signatory = (
        await session.execute(
            select(DocumentSignatory)
            .where(DocumentSignatory.tenant_id == tenant_id)
            .where(DocumentSignatory.id == to_uuid(body.signatory_id))
            .where(col(DocumentSignatory.archived_at).is_(None))
        )
    ).scalar_one_or_none()
    if signatory is None:
        raise HTTPException(422, "Choose a signatory from the list")
    if signatory.legal_entity_id is not None and signatory.legal_entity_id != legal_entity_id:
        where = "this company" if legal_entity_id else "every company"
        raise HTTPException(422, f"{signatory.name} does not sign for {where}")
    return signatory.id


async def _save(
    session,
    tenant_id: UUID,
    legal_entity_id: UUID | None,
    body: PayslipTemplateSave,
    user_id: UUID | None,
) -> PayslipTemplateResponse:
    await lock_resource(session, tenant_id, f"payslip-template:{legal_entity_id or 'group'}")
    signatory_id = await _signatory_id(session, tenant_id, body, legal_entity_id)
    group, company = await templates_for(session, tenant_id, legal_entity_id)
    row = company if legal_entity_id else group
    if row is None:
        row = PayslipTemplate(tenant_id=tenant_id, id=uuid4(), legal_entity_id=legal_entity_id)
    else:
        await require_version(session, row, body.version)
    for name, value in body.model_dump(exclude={"version", "signatory_id"}).items():
        setattr(row, name, value)
    row.signatory_id = signatory_id
    row.recorded_by = user_id
    row.recorded_at = datetime.now(UTC)
    session.add(row)
    await session.flush()
    return _response(row)


@router.get(
    "",
    response_model=PayslipTemplateOverview,
    summary="Payslip templates: the group's and each company's",
)
async def payslip_template_overview(
    tenant_id: TenantDep, session: SessionDep, scope: TemplateScope
) -> PayslipTemplateOverview:
    rows = list(
        (
            await session.execute(
                select(PayslipTemplate).where(PayslipTemplate.tenant_id == tenant_id)
            )
        ).scalars()
    )
    own = {r.legal_entity_id: r for r in rows if r.legal_entity_id}
    companies = (
        await session.execute(
            select(LegalEntity)
            .where(LegalEntity.tenant_id == tenant_id)
            .where(col(LegalEntity.archived_at).is_(None))
            .order_by(col(LegalEntity.name))
        )
    ).scalars()
    return PayslipTemplateOverview(
        group=_response(next((r for r in rows if r.legal_entity_id is None), None)),
        companies=[
            CompanyPayslipTemplate(
                legal_entity_id=to_typed_id("legal_entity", c.id),
                name=c.name,
                template=_response(own[c.id]) if c.id in own else None,
            )
            for c in companies
            if scope.covers_entity(c.id)
        ],
        fields=[EmployeeFieldOption(key=k, label=v) for k, v in document.EMPLOYEE_FIELDS.items()],
    )


@router.put(
    "/group",
    response_model=PayslipTemplateResponse,
    summary="Save the group's payslip template",
)
async def put_group_payslip_template(
    body: PayslipTemplateSave,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: TemplateScope,
) -> PayslipTemplateResponse:
    if not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a group-level administrator can change the group's payslip template",
        )
    return await _save(session, tenant_id, None, body, principal.user_account_id)


@router.put(
    "/companies/{entity_id}",
    response_model=PayslipTemplateResponse,
    summary="Save a company's own payslip template",
)
async def put_company_payslip_template(
    entity_id: str,
    body: PayslipTemplateSave,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: TemplateScope,
) -> PayslipTemplateResponse:
    company = await get_company(session, tenant_id, entity_id)
    if not scope.covers_entity(company.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")
    return await _save(session, tenant_id, company.id, body, principal.user_account_id)


@router.delete(
    "/companies/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Make a company use the group's payslip template again",
)
async def delete_company_payslip_template(
    entity_id: str, tenant_id: TenantDep, session: SessionDep, scope: TemplateScope
) -> Response:
    company = await get_company(session, tenant_id, entity_id)
    if not scope.covers_entity(company.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")
    _, row = await templates_for(session, tenant_id, company.id)
    if row is not None:
        await session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/preview",
    summary="Preview a payslip template as a SAMPLE PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}, "image/png": {}}}},
)
async def preview_payslip_template(
    body: PayslipPreviewRequest,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: TemplateScope,
    format: Literal["pdf", "png"] = Query(
        default="pdf", description="pdf, or png: every page as one image, for showing on screen"
    ),
) -> Response:
    entity_id = None
    prefix = "SAMPLE"
    if body.legal_entity_id:
        company = await get_company(session, tenant_id, body.legal_entity_id)
        if not scope.covers_entity(company.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")
        entity_id = company.id
        prefix = (company.short_name or "SAMPLE").upper()
    signatory_id = await _signatory_id(session, tenant_id, body.template, entity_id)
    issuer = await issuer_for(session, tenant_id, entity_id, signatory_id)
    now = to_tz(now_utc(), settings.default_timezone)
    data = sample.sample_payslip(business_today(), now, prefix)
    view = document.build_view(data, issuer, settings_of(body.template), sample=True)
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if format == "png":
        png = await run_in_threadpool(render.render_png, view)
        return Response(png, media_type="image/png", headers=headers)
    pdf = await run_in_threadpool(render.render_pdf, view)
    headers["Content-Disposition"] = 'inline; filename="payslip-sample.pdf"'
    return Response(pdf, media_type="application/pdf", headers=headers)

"""Who issues a payslip, as printed: the company's details with its resolved branding."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from hrms.modules.branding import resolve
from hrms.modules.branding.models import BrandAsset, DocumentSignatory
from hrms.modules.payroll.payslip.document import Issuer, Signer


def _address(company) -> str | None:
    place = " ".join(p for p in (company.state_code, company.pincode) if p)
    parts = [company.address_line1, company.address_line2, company.city, place]
    return ", ".join(p for p in parts if p) or None


def _registrations(company) -> tuple[tuple[str, str], ...]:
    labelled = (
        ("CIN", company.cin),
        ("TAN", company.tan),
        ("PF code", company.pf_establishment_code),
        ("ESIC code", company.esic_employer_code),
    )
    return tuple((label, value) for label, value in labelled if value)


async def signer_for(session, tenant_id: UUID, signatory_id: UUID | None) -> Signer | None:
    if signatory_id is None:
        return None
    signatory = (
        await session.execute(
            select(DocumentSignatory)
            .where(DocumentSignatory.tenant_id == tenant_id)
            .where(DocumentSignatory.id == signatory_id)
        )
    ).scalar_one_or_none()
    if signatory is None:
        return None
    png = None
    if signatory.signature_asset_id:
        asset = await session.get(BrandAsset, (tenant_id, signatory.signature_asset_id))
        png = await run_in_threadpool(resolve.load_png, asset) if asset else None
    return Signer(name=signatory.name, designation=signatory.designation, signature_png=png)


async def issuer_for(
    session, tenant_id: UUID, legal_entity_id: UUID | None, signatory_id: UUID | None
) -> Issuer:
    context = await resolve.context(session, tenant_id, legal_entity_id)
    company = context.company
    logo = await run_in_threadpool(resolve.load_png, context.logo) if context.logo else None
    contact = tuple(
        v for v in (context.value(n) for n in ("contact_email", "contact_phone", "website")) if v
    )
    return Issuer(
        name=company.registered_name or company.name,
        address=_address(company),
        registrations=_registrations(company),
        logo_png=logo,
        primary_color=context.value("primary_color") or resolve.DEFAULTS["primary_color"],
        accent_color=context.value("accent_color") or resolve.DEFAULTS["accent_color"],
        footer_text=context.value("footer_text"),
        contact=contact,
        signer=await signer_for(session, tenant_id, signatory_id),
    )

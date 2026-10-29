"""
Branding — /v1/branding. How payslips (and later letters) look, per group and per company.

Profiles     GET /profiles   PUT /profiles/group   PUT|DELETE /profiles/companies/{entity_id}
Resolved     GET /resolved?legal_entity_id=   what applies, field by field, and where it comes from
Images       POST /assets (logo or signature)   GET /assets/{asset_id}/image
Signatories  GET/POST /signatories   PATCH /signatories/{id}   POST /signatories/{id}/archive

Access: org.read to see, org.write to change (HR and Admin). The group default needs a
group-level (ALL) org.write; a company's own values need org.write covering that company.
Signature images are shown only to org.write. Payroll staff who design the payslip
(payroll.write) may see logos and the signatory list, and never change them.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlmodel import col, select
from starlette.concurrency import run_in_threadpool

from hrms.core import document_store
from hrms.core.authn import CurrentUser
from hrms.core.authz import Scope, ScopeDep, merge_scopes, require_permission
from hrms.core.database import SessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.locking import lock_resource
from hrms.core.tenancy import TenantDep
from hrms.core.versioning import require_version
from hrms.modules.branding import images, resolve
from hrms.modules.branding.models import AssetKind, BrandAsset, BrandProfile, DocumentSignatory
from hrms.modules.branding.schemas import (
    BrandAssetResponse,
    BrandProfileInput,
    BrandProfileResponse,
    ColorCheck,
    ResolvedBranding,
    ResolvedField,
    SignatoryInput,
    SignatoryResponse,
    SignatoryUpdate,
)
from hrms.modules.org.models import LegalEntity

router = APIRouter(prefix="/v1/branding", tags=["Branding"])


# ─── Helpers ─────────────────────────────────────────────────────────────────


def asset_response(asset: BrandAsset) -> BrandAssetResponse:
    return BrandAssetResponse(
        id=to_typed_id("brand_asset", asset.id),
        kind=AssetKind(asset.kind),
        file_name=asset.file_name,
        width=asset.width,
        height=asset.height,
        byte_size=asset.byte_size,
        uploaded_at=asset.uploaded_at,
    )


async def _assets(session, tenant_id: UUID, ids: set[UUID | None]) -> dict[UUID, BrandAsset]:
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    rows = await session.execute(
        select(BrandAsset)
        .where(BrandAsset.tenant_id == tenant_id)
        .where(col(BrandAsset.id).in_(wanted))
    )
    return {a.id: a for a in rows.scalars()}


async def asset_of_kind(session, tenant_id: UUID, typed_id: str | None, kind: AssetKind):
    """The tenant's asset of this kind, or 422 (an unknown id, or a logo used as a signature)."""
    if typed_id is None:
        return None
    asset = (await _assets(session, tenant_id, {to_uuid(typed_id)})).get(to_uuid(typed_id))
    if asset is None or asset.kind != kind:
        label = "logo" if kind == AssetKind.LOGO else "signature image"
        raise HTTPException(422, f"Upload the {label} first, then choose it")
    return asset


async def get_company(session, tenant_id: UUID, typed_id: str) -> LegalEntity:
    row = await session.execute(
        select(LegalEntity)
        .where(LegalEntity.tenant_id == tenant_id)
        .where(LegalEntity.id == to_uuid(typed_id))
        .where(col(LegalEntity.archived_at).is_(None))
    )
    entity = row.scalars().first()
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return entity


def _require_group(scope: Scope, what: str) -> None:
    if not scope.is_all:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Only a group-level administrator can change {what}"
        )


def _require_company(scope: Scope, entity_id: UUID) -> None:
    if not scope.covers_entity(entity_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this company")


def _read_scope(scope: Scope, *permissions: str) -> Scope:
    """The scope of whichever of these permissions the caller holds (403 if none)."""
    held = [p for p in permissions if scope.has(p)]
    if not held:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Missing permission: {' or '.join(permissions)}"
        )
    return merge_scopes([scope.for_permission(p) for p in held], scope.own_employment_id)


def _profile_response(row: BrandProfile, assets: dict[UUID, BrandAsset]) -> BrandProfileResponse:
    logo = assets.get(row.logo_asset_id) if row.logo_asset_id else None
    return BrandProfileResponse(
        id=to_typed_id("brand_profile", row.id),
        legal_entity_id=to_typed_id("legal_entity", row.legal_entity_id)
        if row.legal_entity_id
        else None,
        logo=asset_response(logo) if logo else None,
        primary_color=row.primary_color,
        accent_color=row.accent_color,
        footer_text=row.footer_text,
        contact_email=row.contact_email,
        contact_phone=row.contact_phone,
        website=row.website,
        version=row.version,
        recorded_at=row.recorded_at,
    )


async def _save_profile(
    session,
    tenant_id: UUID,
    legal_entity_id: UUID | None,
    body: BrandProfileInput,
    user_id: UUID | None,
) -> BrandProfileResponse:
    await lock_resource(session, tenant_id, f"branding:profile:{legal_entity_id or 'group'}")
    logo = await asset_of_kind(session, tenant_id, body.logo_asset_id, AssetKind.LOGO)
    group, company = await resolve.profiles_for(session, tenant_id, legal_entity_id)
    row = company if legal_entity_id else group
    if row is None:
        row = BrandProfile(tenant_id=tenant_id, id=uuid4(), legal_entity_id=legal_entity_id)
    else:
        await require_version(session, row, body.version)
    values = body.model_dump(exclude={"version", "logo_asset_id"})
    for name, value in values.items():
        setattr(row, name, value)
    row.logo_asset_id = logo.id if logo else None
    row.recorded_by = user_id
    row.recorded_at = datetime.now(UTC)
    session.add(row)
    await session.flush()
    return _profile_response(row, {logo.id: logo} if logo else {})


# ─── Profiles ────────────────────────────────────────────────────────────────


@router.get(
    "/profiles",
    response_model=list[BrandProfileResponse],
    summary="Branding saved for the group and companies",
    dependencies=[require_permission("org.read")],
)
async def list_brand_profiles(
    tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> list[BrandProfileResponse]:
    scope = scope.for_permission("org.read")
    rows = [
        r
        for r in (
            await session.execute(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id))
        ).scalars()
        if r.legal_entity_id is None or scope.covers_entity(r.legal_entity_id)
    ]
    assets = await _assets(session, tenant_id, {r.logo_asset_id for r in rows})
    rows.sort(key=lambda r: (r.legal_entity_id is not None, str(r.legal_entity_id)))
    return [_profile_response(r, assets) for r in rows]


@router.put(
    "/profiles/group",
    response_model=BrandProfileResponse,
    summary="Set the group's default branding",
    dependencies=[require_permission("org.write")],
)
async def put_group_brand_profile(
    body: BrandProfileInput,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> BrandProfileResponse:
    _require_group(scope.for_permission("org.write"), "the group's branding")
    return await _save_profile(session, tenant_id, None, body, principal.user_account_id)


@router.put(
    "/profiles/companies/{entity_id}",
    response_model=BrandProfileResponse,
    summary="Set a company's own branding",
    dependencies=[require_permission("org.write")],
)
async def put_company_brand_profile(
    entity_id: str,
    body: BrandProfileInput,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> BrandProfileResponse:
    company = await get_company(session, tenant_id, entity_id)
    _require_company(scope.for_permission("org.write"), company.id)
    return await _save_profile(session, tenant_id, company.id, body, principal.user_account_id)


@router.delete(
    "/profiles/companies/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Make a company use the group's branding again",
    dependencies=[require_permission("org.write")],
)
async def delete_company_brand_profile(
    entity_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> Response:
    company = await get_company(session, tenant_id, entity_id)
    _require_company(scope.for_permission("org.write"), company.id)
    _, row = await resolve.profiles_for(session, tenant_id, company.id)
    if row is not None:
        await session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/resolved",
    response_model=ResolvedBranding,
    summary="The branding that applies to a company, field by field",
    dependencies=[require_permission("org.read")],
)
async def resolved_branding(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    legal_entity_id: str | None = Query(default=None, description="Omit for the group default"),
) -> ResolvedBranding:
    entity_uuid = None
    if legal_entity_id:
        company = await get_company(session, tenant_id, legal_entity_id)
        _require_company(scope.for_permission("org.read"), company.id)
        entity_uuid = company.id
    context = await resolve.context(session, tenant_id, entity_uuid)
    primary = str(context.fields["primary_color"].value)
    text_color = resolve.readable_on_white(primary)
    return ResolvedBranding(
        legal_entity_id=legal_entity_id,
        company=context.company,
        fields={
            name: ResolvedField(
                value=to_typed_id("brand_asset", v.value)
                if name == "logo_asset_id" and isinstance(v.value, UUID)
                else (None if v.value is None else str(v.value)),
                source=v.source,
            )
            for name, v in context.fields.items()
        },
        logo=asset_response(context.logo) if context.logo else None,
        color_check=ColorCheck(
            text_color=text_color,
            adjusted=text_color != primary.upper(),
            contrast=round(resolve.contrast(text_color, resolve.WHITE), 2),
        ),
    )


# ─── Images ──────────────────────────────────────────────────────────────────


@router.post(
    "/assets",
    response_model=BrandAssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a logo or signature image",
    dependencies=[require_permission("org.write")],
)
async def upload_brand_asset(
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    kind: AssetKind = Form(...),
    file: UploadFile = File(...),
) -> BrandAssetResponse:
    content = await file.read(images.MAX_UPLOAD_BYTES + 1)
    try:
        image = await run_in_threadpool(images.normalize, content, kind)
    except images.ImageRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    digest = hashlib.sha256(image.png).hexdigest()
    existing = await session.execute(
        select(BrandAsset)
        .where(BrandAsset.tenant_id == tenant_id)
        .where(BrandAsset.kind == kind.value)
        .where(BrandAsset.sha256 == digest)
    )
    if (same := existing.scalars().first()) is not None:
        return asset_response(same)  # the same picture uploaded again
    asset_id = uuid4()
    # Encrypted before it is stored; removed again if the transaction rolls back.
    ref = await run_in_threadpool(
        document_store.save, f"branding/{tenant_id}/{asset_id}.png", image.png
    )
    session.info.setdefault("created_files", []).append(ref)
    name = (file.filename or "image").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:255] or "image"
    asset = BrandAsset(
        tenant_id=tenant_id,
        id=asset_id,
        kind=kind.value,
        file_name=name,
        width=image.width,
        height=image.height,
        byte_size=len(image.png),
        sha256=digest,
        storage_ref=ref,
        uploaded_by=principal.user_account_id,
    )
    session.add(asset)
    await session.flush()
    return asset_response(asset)


@router.get(
    "/assets/{asset_id}/image",
    summary="A logo or signature image (PNG)",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def brand_asset_image(
    asset_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> Response:
    asset = (await _assets(session, tenant_id, {to_uuid(asset_id)})).get(to_uuid(asset_id))
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if asset.kind == AssetKind.SIGNATURE:
        # A signature can be misused; only the people who manage signatories see it.
        scope.require("org.write")
    else:
        _read_scope(scope, "org.read", "payroll.write")
    content = await run_in_threadpool(resolve.load_png, asset)
    return Response(
        content,
        media_type="image/png",
        headers={
            # Images never change (a new upload is a new id), so a logo may be cached.
            "Cache-Control": "no-store"
            if asset.kind == AssetKind.SIGNATURE
            else "private, max-age=86400, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


# ─── Signatories ─────────────────────────────────────────────────────────────


async def _signatory_response(session, tenant_id, rows: list[DocumentSignatory]):
    assets = await _assets(session, tenant_id, {r.signature_asset_id for r in rows})
    return [
        SignatoryResponse(
            id=to_typed_id("document_signatory", r.id),
            legal_entity_id=to_typed_id("legal_entity", r.legal_entity_id)
            if r.legal_entity_id
            else None,
            name=r.name,
            designation=r.designation,
            signature=asset_response(assets[r.signature_asset_id])
            if r.signature_asset_id in assets
            else None,
            version=r.version,
        )
        for r in rows
    ]


async def _get_signatory(session, tenant_id: UUID, signatory_id: str) -> DocumentSignatory:
    row = await session.execute(
        select(DocumentSignatory)
        .where(DocumentSignatory.tenant_id == tenant_id)
        .where(DocumentSignatory.id == to_uuid(signatory_id))
        .where(col(DocumentSignatory.archived_at).is_(None))
    )
    signatory = row.scalars().first()
    if signatory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signatory not found")
    return signatory


async def _check_signatory_scope(session, tenant_id, scope: Scope, body: SignatoryInput):
    if body.legal_entity_id is None:
        _require_group(scope, "a signatory for every company")
        return None
    company = await get_company(session, tenant_id, body.legal_entity_id)
    _require_company(scope, company.id)
    return company.id


def _covers_signatory(scope: Scope, row: DocumentSignatory) -> bool:
    return row.legal_entity_id is None or scope.covers_entity(row.legal_entity_id)


@router.get(
    "/signatories",
    response_model=list[SignatoryResponse],
    summary="People who sign documents",
)
async def list_signatories(
    tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> list[SignatoryResponse]:
    scope = _read_scope(scope, "org.write", "payroll.write")
    rows = [
        r
        for r in (
            await session.execute(
                select(DocumentSignatory)
                .where(DocumentSignatory.tenant_id == tenant_id)
                .where(col(DocumentSignatory.archived_at).is_(None))
                .order_by(col(DocumentSignatory.name))
            )
        ).scalars()
        if _covers_signatory(scope, r)
    ]
    return await _signatory_response(session, tenant_id, rows)


@router.post(
    "/signatories",
    response_model=SignatoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a signatory",
    dependencies=[require_permission("org.write")],
)
async def create_signatory(
    body: SignatoryInput,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> SignatoryResponse:
    entity_id = await _check_signatory_scope(
        session, tenant_id, scope.for_permission("org.write"), body
    )
    signature = await asset_of_kind(
        session, tenant_id, body.signature_asset_id, AssetKind.SIGNATURE
    )
    row = DocumentSignatory(
        tenant_id=tenant_id,
        id=uuid4(),
        legal_entity_id=entity_id,
        name=body.name.strip(),
        designation=body.designation,
        signature_asset_id=signature.id if signature else None,
        recorded_by=principal.user_account_id,
    )
    session.add(row)
    await session.flush()
    return (await _signatory_response(session, tenant_id, [row]))[0]


@router.patch(
    "/signatories/{signatory_id}",
    response_model=SignatoryResponse,
    summary="Change a signatory",
    dependencies=[require_permission("org.write")],
)
async def update_signatory(
    signatory_id: str,
    body: SignatoryUpdate,
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> SignatoryResponse:
    scope = scope.for_permission("org.write")
    row = await _get_signatory(session, tenant_id, signatory_id)
    if not _covers_signatory(scope, row):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this signatory")
    entity_id = await _check_signatory_scope(session, tenant_id, scope, body)
    signature = await asset_of_kind(
        session, tenant_id, body.signature_asset_id, AssetKind.SIGNATURE
    )
    await require_version(session, row, body.version)
    row.legal_entity_id = entity_id
    row.name = body.name.strip()
    row.designation = body.designation
    row.signature_asset_id = signature.id if signature else None
    row.recorded_by = principal.user_account_id
    row.recorded_at = datetime.now(UTC)
    session.add(row)
    await session.flush()
    return (await _signatory_response(session, tenant_id, [row]))[0]


@router.post(
    "/signatories/{signatory_id}/archive",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire a signatory",
    dependencies=[require_permission("org.write")],
)
async def archive_signatory(
    signatory_id: str, tenant_id: TenantDep, session: SessionDep, scope: ScopeDep
) -> Response:
    from hrms.modules.payroll.models import PayslipTemplate

    row = await _get_signatory(session, tenant_id, signatory_id)
    if not _covers_signatory(scope.for_permission("org.write"), row):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this signatory")
    in_use = await session.execute(
        select(PayslipTemplate.id)
        .where(PayslipTemplate.tenant_id == tenant_id)
        .where(PayslipTemplate.signatory_id == row.id)
        .limit(1)
    )
    if in_use.first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A payslip template signs with this person. Choose another signatory there first.",
        )
    row.archived_at = datetime.now(UTC)
    session.add(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

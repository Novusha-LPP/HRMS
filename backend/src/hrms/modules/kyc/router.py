"""Employee KYC router: Handles self-service and HR-managed KYC workflows."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlmodel import select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, authorize_employment, require_permission
from hrms.core.config import settings
from hrms.core.database import SessionDep
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.kyc.models import (
    DocumentStatus,
    EmployeeKycDocument,
    EmployeeKycRecord,
    KycStatus,
)
from hrms.modules.kyc.schemas import (
    KycDocumentResponse,
    KycEmployeeListItem,
    KycRecordResponse,
    KycRecordUpdateRequest,
    KycSummaryStats,
    VerifyDocumentRequest,
    VerifyOverallKycRequest,
)

router = APIRouter(prefix="/v1/kyc", tags=["Employee KYC"])


def _storage_dir_for_tenant(tenant_id: UUID) -> Path:
    base = Path(settings.storage_dir) / "kyc" / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _clean_filename(filename: str) -> str:
    cleaned = re.sub(r"[^\w\.-]", "_", filename)
    return cleaned[:100]


def _calc_completion(rec: EmployeeKycRecord, docs: list[EmployeeKycDocument]) -> int:
    score = 0
    total = 8

    # 1. PAN number
    if rec.pan_number and len(rec.pan_number.strip()) >= 5:
        score += 1
    # 2. Aadhaar number
    if rec.aadhaar_number and len(rec.aadhaar_number.strip()) >= 4:
        score += 1
    # 3. Bank details
    if rec.bank_name and rec.account_number and rec.ifsc_code:
        score += 1
    # 4. Current address
    if rec.current_address and len(rec.current_address.strip()) >= 5:
        score += 1
    # 5. Emergency contact
    if rec.emergency_contact_name and rec.emergency_contact_phone:
        score += 1

    doc_types = {d.document_type for d in docs}
    # 6. PAN Card document
    if "PAN_CARD" in doc_types:
        score += 1
    # 7. Aadhaar document (Front or back)
    if "AADHAAR_FRONT" in doc_types or "AADHAAR_BACK" in doc_types:
        score += 1
    # 8. Bank proof document
    if "BANK_PROOF" in doc_types:
        score += 1

    return min(100, int((score / total) * 100))


def _to_doc_response(doc: EmployeeKycDocument) -> KycDocumentResponse:
    doc_typed_id = to_typed_id("kyc_document", doc.id)
    return KycDocumentResponse(
        id=doc_typed_id,
        employment_id=to_typed_id("employment", doc.employment_id),
        document_type=doc.document_type,
        document_title=doc.document_title,
        document_number=doc.document_number,
        file_name=doc.file_name,
        file_size=doc.file_size,
        mime_type=doc.mime_type,
        status=doc.status,
        rejection_reason=doc.rejection_reason,
        comments=doc.comments,
        uploaded_at=doc.uploaded_at,
        verified_at=doc.verified_at,
        download_url=f"/v1/kyc/documents/{doc_typed_id}/download",
        preview_url=f"/v1/kyc/documents/{doc_typed_id}/preview",
    )


async def _get_employee_meta(session: SessionDep, tenant_id: UUID, employment_id: UUID) -> dict[str, Optional[str]]:
    rows = await session.execute(
        text("""
            SELECT
                e.employee_number,
                p.legal_first_name || ' ' || p.legal_last_name AS employee_name,
                ou.name AS department,
                j.title AS designation,
                p.id AS person_id
            FROM employments e
            LEFT JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
            LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id AND a.effective_to IS NULL
            LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
            LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
            WHERE e.tenant_id = CAST(:tid AS uuid)
              AND e.id = CAST(:eid AS uuid)
            LIMIT 1
        """),
        {"tid": str(tenant_id), "eid": str(employment_id)},
    )
    row = rows.first()
    if not row:
        return {"employee_number": None, "employee_name": None, "department": None, "designation": None, "person_id": None}
    return {
        "employee_number": row[0],
        "employee_name": row[1],
        "department": row[2],
        "designation": row[3],
        "person_id": row[4],
    }


async def _get_or_create_record(
    session: SessionDep, tenant_id: UUID, employment_id: UUID
) -> EmployeeKycRecord:
    res = await session.execute(
        select(EmployeeKycRecord)
        .where(EmployeeKycRecord.tenant_id == tenant_id)
        .where(EmployeeKycRecord.employment_id == employment_id)
    )
    rec = res.scalars().first()
    if rec:
        return rec

    meta = await _get_employee_meta(session, tenant_id, employment_id)
    rec = EmployeeKycRecord(
        tenant_id=tenant_id,
        id=uuid4(),
        employment_id=employment_id,
        person_id=meta["person_id"],
        status=KycStatus.NOT_SUBMITTED,
        updated_at=datetime.now(timezone.utc),
    )
    session.add(rec)
    await session.flush()
    return rec


# ─── Employee Self-Service ───────────────────────────────────────────────────

@router.get("/me", response_model=KycRecordResponse, summary="Get own KYC record and documents")
async def get_my_kyc(
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> KycRecordResponse:
    if not user.employment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current account does not have an associated employment record",
        )

    rec = await _get_or_create_record(session, tenant_id, user.employment_id)
    meta = await _get_employee_meta(session, tenant_id, user.employment_id)

    docs_res = await session.execute(
        select(EmployeeKycDocument)
        .where(EmployeeKycDocument.tenant_id == tenant_id)
        .where(EmployeeKycDocument.employment_id == user.employment_id)
        .order_by(EmployeeKycDocument.uploaded_at.desc())  # type: ignore
    )
    docs = list(docs_res.scalars())
    doc_responses = [_to_doc_response(d) for d in docs]
    completion = _calc_completion(rec, docs)

    return KycRecordResponse(
        id=to_typed_id("kyc_record", rec.id),
        employment_id=to_typed_id("employment", rec.employment_id),
        employee_name=meta["employee_name"],
        employee_number=meta["employee_number"],
        department=meta["department"],
        designation=meta["designation"],
        pan_number=rec.pan_number,
        aadhaar_number=rec.aadhaar_number,
        uan_number=rec.uan_number,
        pf_number=rec.pf_number,
        esi_number=rec.esi_number,
        passport_number=rec.passport_number,
        passport_expiry=rec.passport_expiry,
        driving_license=rec.driving_license,
        voter_id=rec.voter_id,
        bank_name=rec.bank_name,
        account_holder_name=rec.account_holder_name,
        account_number=rec.account_number,
        ifsc_code=rec.ifsc_code,
        branch_name=rec.branch_name,
        father_or_spouse_name=rec.father_or_spouse_name,
        marital_status=rec.marital_status,
        blood_group=rec.blood_group,
        emergency_contact_name=rec.emergency_contact_name,
        emergency_contact_relation=rec.emergency_contact_relation,
        emergency_contact_phone=rec.emergency_contact_phone,
        current_address=rec.current_address,
        permanent_address=rec.permanent_address,
        status=rec.status,
        submitted_at=rec.submitted_at,
        verified_at=rec.verified_at,
        rejection_reason=rec.rejection_reason,
        updated_at=rec.updated_at,
        documents=doc_responses,
        completion_percentage=completion,
    )


@router.patch("/me", response_model=KycRecordResponse, summary="Update own KYC details")
async def update_my_kyc(
    body: KycRecordUpdateRequest,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> KycRecordResponse:
    if not user.employment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current account does not have an associated employment record",
        )

    rec = await _get_or_create_record(session, tenant_id, user.employment_id)

    # Update fields provided in request
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(rec, field, val)

    if rec.status == KycStatus.NOT_SUBMITTED:
        rec.status = KycStatus.DRAFT
    elif rec.status == KycStatus.REJECTED:
        rec.status = KycStatus.DRAFT

    rec.updated_at = datetime.now(timezone.utc)
    rec.updated_by = user.user_account_id
    rec.version += 1
    session.add(rec)
    await session.flush()

    return await get_my_kyc(user, tenant_id, session)


@router.post("/me/submit", response_model=KycRecordResponse, summary="Submit own KYC for verification")
async def submit_my_kyc(
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> KycRecordResponse:
    if not user.employment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current account does not have an associated employment record",
        )

    rec = await _get_or_create_record(session, tenant_id, user.employment_id)
    rec.status = KycStatus.SUBMITTED
    rec.submitted_at = datetime.now(timezone.utc)
    rec.updated_at = datetime.now(timezone.utc)
    rec.updated_by = user.user_account_id
    rec.version += 1
    session.add(rec)
    await session.flush()

    return await get_my_kyc(user, tenant_id, session)


@router.post("/me/documents", response_model=KycDocumentResponse, summary="Upload a KYC document for yourself")
async def upload_my_document(
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    document_title: str = Form(...),
    document_number: Optional[str] = Form(None),
) -> KycDocumentResponse:
    if not user.employment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current account does not have an associated employment record",
        )

    return await _save_uploaded_doc(
        session=session,
        tenant_id=tenant_id,
        employment_id=user.employment_id,
        uploaded_by=user.user_account_id,
        file=file,
        document_type=document_type,
        document_title=document_title,
        document_number=document_number,
    )


# ─── HR & Admin Endpoints ────────────────────────────────────────────────────

@router.get("/summary", response_model=KycSummaryStats, summary="Overall KYC metrics for HR")
async def get_kyc_summary(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> KycSummaryStats:
    scope.require("people.read")
    flt, params = scope.employment_filter_sql("e")

    query = text(f"""
        SELECT
            COUNT(e.id) AS total,
            COUNT(k.id) FILTER (WHERE k.status = 'VERIFIED') AS verified,
            COUNT(k.id) FILTER (WHERE k.status = 'SUBMITTED') AS pending_review,
            COUNT(e.id) FILTER (WHERE k.id IS NULL OR k.status IN ('NOT_SUBMITTED', 'DRAFT', 'ACTION_REQUIRED')) AS incomplete,
            COUNT(k.id) FILTER (WHERE k.status = 'REJECTED') AS rejected
        FROM employments e
        LEFT JOIN employee_kyc_records k
            ON k.tenant_id = e.tenant_id AND k.employment_id = e.id
        WHERE e.tenant_id = CAST(:tid AS uuid)
          AND e.archived_at IS NULL
          {flt}
    """)
    bind_params = {"tid": str(tenant_id), **params}
    res = await session.execute(query, bind_params)
    row = res.first()
    if not row:
        return KycSummaryStats(
            total_employees=0,
            verified_count=0,
            pending_verification_count=0,
            incomplete_count=0,
            rejected_count=0,
        )

    return KycSummaryStats(
        total_employees=row[0] or 0,
        verified_count=row[1] or 0,
        pending_verification_count=row[2] or 0,
        incomplete_count=row[3] or 0,
        rejected_count=row[4] or 0,
    )


@router.get("/employees", response_model=list[KycEmployeeListItem], summary="List employee KYC statuses for HR")
async def list_employees_kyc(
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
) -> list[KycEmployeeListItem]:
    scope.require("people.read")
    flt, params = scope.employment_filter_sql("e")

    extra_clauses = []
    bind_params = {"tid": str(tenant_id), **params}

    if status_filter:
        if status_filter == "INCOMPLETE":
            extra_clauses.append("AND (k.status IS NULL OR k.status IN ('NOT_SUBMITTED', 'DRAFT', 'ACTION_REQUIRED'))")
        else:
            extra_clauses.append("AND k.status = :status_filter")
            bind_params["status_filter"] = status_filter

    if search:
        extra_clauses.append("""
            AND (
                LOWER(e.employee_number) LIKE LOWER(:search)
                OR LOWER(p.legal_first_name || ' ' || p.legal_last_name) LIKE LOWER(:search)
            )
        """)
        bind_params["search"] = f"%{search}%"

    extra_sql = " ".join(extra_clauses)

    query = text(f"""
        SELECT
            e.id AS employment_id,
            e.employee_number,
            p.legal_first_name || ' ' || p.legal_last_name AS employee_name,
            ou.name AS department,
            j.title AS designation,
            COALESCE(k.status, 'NOT_SUBMITTED') AS kyc_status,
            COALESCE(k.updated_at, e.recorded_at) AS updated_at,
            (SELECT COUNT(*) FROM employee_kyc_documents d WHERE d.tenant_id = e.tenant_id AND d.employment_id = e.id) AS docs_count,
            (SELECT COUNT(*) FROM employee_kyc_documents d WHERE d.tenant_id = e.tenant_id AND d.employment_id = e.id AND d.status = 'VERIFIED') AS verified_docs_count,
            k.pan_number, k.aadhaar_number, k.bank_name, k.account_number, k.ifsc_code, k.current_address, k.emergency_contact_name, k.emergency_contact_phone
        FROM employments e
        JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
        LEFT JOIN assignments a ON a.tenant_id = e.tenant_id AND a.employment_id = e.id AND a.effective_to IS NULL
        LEFT JOIN org_units ou ON ou.tenant_id = a.tenant_id AND ou.id = a.org_unit_id
        LEFT JOIN jobs j ON j.tenant_id = a.tenant_id AND j.id = a.job_id
        LEFT JOIN employee_kyc_records k ON k.tenant_id = e.tenant_id AND k.employment_id = e.id
        WHERE e.tenant_id = CAST(:tid AS uuid)
          AND e.archived_at IS NULL
          {flt}
          {extra_sql}
        ORDER BY
            CASE WHEN COALESCE(k.status, 'NOT_SUBMITTED') = 'SUBMITTED' THEN 0
                 WHEN COALESCE(k.status, 'NOT_SUBMITTED') = 'REJECTED' THEN 1
                 WHEN COALESCE(k.status, 'NOT_SUBMITTED') IN ('DRAFT', 'NOT_SUBMITTED') THEN 2
                 ELSE 3 END,
            employee_name ASC
        LIMIT :limit
    """)
    bind_params["limit"] = limit

    rows = await session.execute(query, bind_params)
    items = []
    for r in rows:
        # compute simple completion
        score = 0
        if r[9] and len(str(r[9]).strip()) >= 5: score += 1
        if r[10] and len(str(r[10]).strip()) >= 4: score += 1
        if r[11] and r[12] and r[13]: score += 1
        if r[14]: score += 1
        if r[15] and r[16]: score += 1
        docs_count = r[7] or 0
        if docs_count >= 1: score += 1
        if docs_count >= 2: score += 1
        if docs_count >= 3: score += 1
        comp = min(100, int((score / 8) * 100))

        items.append(KycEmployeeListItem(
            employment_id=to_typed_id("employment", r[0]),
            employee_number=r[1],
            employee_name=r[2],
            department=r[3],
            designation=r[4],
            kyc_status=r[5],
            updated_at=r[6],
            documents_count=docs_count,
            verified_documents_count=r[8] or 0,
            completion_percentage=comp,
        ))

    return items


@router.get("/employees/{employment_id}", response_model=KycRecordResponse, summary="HR view of employee KYC dossier")
async def get_employee_kyc(
    employment_id: str,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> KycRecordResponse:
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)

    rec = await _get_or_create_record(session, tenant_id, emp_uuid)
    meta = await _get_employee_meta(session, tenant_id, emp_uuid)

    docs_res = await session.execute(
        select(EmployeeKycDocument)
        .where(EmployeeKycDocument.tenant_id == tenant_id)
        .where(EmployeeKycDocument.employment_id == emp_uuid)
        .order_by(EmployeeKycDocument.uploaded_at.desc())  # type: ignore
    )
    docs = list(docs_res.scalars())
    doc_responses = [_to_doc_response(d) for d in docs]
    completion = _calc_completion(rec, docs)

    return KycRecordResponse(
        id=to_typed_id("kyc_record", rec.id),
        employment_id=to_typed_id("employment", rec.employment_id),
        employee_name=meta["employee_name"],
        employee_number=meta["employee_number"],
        department=meta["department"],
        designation=meta["designation"],
        pan_number=rec.pan_number,
        aadhaar_number=rec.aadhaar_number,
        uan_number=rec.uan_number,
        pf_number=rec.pf_number,
        esi_number=rec.esi_number,
        passport_number=rec.passport_number,
        passport_expiry=rec.passport_expiry,
        driving_license=rec.driving_license,
        voter_id=rec.voter_id,
        bank_name=rec.bank_name,
        account_holder_name=rec.account_holder_name,
        account_number=rec.account_number,
        ifsc_code=rec.ifsc_code,
        branch_name=rec.branch_name,
        father_or_spouse_name=rec.father_or_spouse_name,
        marital_status=rec.marital_status,
        blood_group=rec.blood_group,
        emergency_contact_name=rec.emergency_contact_name,
        emergency_contact_relation=rec.emergency_contact_relation,
        emergency_contact_phone=rec.emergency_contact_phone,
        current_address=rec.current_address,
        permanent_address=rec.permanent_address,
        status=rec.status,
        submitted_at=rec.submitted_at,
        verified_at=rec.verified_at,
        rejection_reason=rec.rejection_reason,
        updated_at=rec.updated_at,
        documents=doc_responses,
        completion_percentage=completion,
    )


@router.patch("/employees/{employment_id}", response_model=KycRecordResponse, summary="HR edit employee KYC details")
async def update_employee_kyc(
    employment_id: str,
    body: KycRecordUpdateRequest,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> KycRecordResponse:
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    if not (scope.has("kyc.write") or scope.has("people.write")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing kyc.write permission")

    rec = await _get_or_create_record(session, tenant_id, emp_uuid)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(rec, field, val)

    rec.updated_at = datetime.now(timezone.utc)
    rec.updated_by = user.user_account_id
    rec.version += 1
    session.add(rec)
    await session.flush()

    return await get_employee_kyc(employment_id, tenant_id, session, scope)


@router.post("/employees/{employment_id}/documents", response_model=KycDocumentResponse, summary="HR upload document for employee")
async def upload_employee_document(
    employment_id: str,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    document_title: str = Form(...),
    document_number: Optional[str] = Form(None),
) -> KycDocumentResponse:
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    if not (scope.has("kyc.write") or scope.has("people.write")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing kyc.write permission")

    return await _save_uploaded_doc(
        session=session,
        tenant_id=tenant_id,
        employment_id=emp_uuid,
        uploaded_by=user.user_account_id,
        file=file,
        document_type=document_type,
        document_title=document_title,
        document_number=document_number,
    )


@router.patch("/documents/{document_id}/verify", response_model=KycDocumentResponse, summary="HR verify or reject a document")
async def verify_document(
    document_id: str,
    body: VerifyDocumentRequest,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> KycDocumentResponse:
    doc_uuid = to_uuid(document_id)
    res = await session.execute(
        select(EmployeeKycDocument)
        .where(EmployeeKycDocument.tenant_id == tenant_id)
        .where(EmployeeKycDocument.id == doc_uuid)
    )
    doc = res.scalars().first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    await authorize_employment(session, tenant_id, scope, doc.employment_id)
    if not (scope.has("kyc.verify") or scope.has("people.write")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing kyc.verify permission")

    if body.status not in (DocumentStatus.VERIFIED, DocumentStatus.REJECTED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status; must be VERIFIED or REJECTED")

    doc.status = body.status
    doc.rejection_reason = body.rejection_reason if body.status == DocumentStatus.REJECTED else None
    if body.comments:
        doc.comments = body.comments
    doc.verified_by = user.user_account_id
    doc.verified_at = datetime.now(timezone.utc)
    doc.version += 1
    session.add(doc)
    await session.flush()

    return _to_doc_response(doc)


@router.post("/employees/{employment_id}/verify", response_model=KycRecordResponse, summary="HR overall verify or reject KYC")
async def verify_overall_kyc(
    employment_id: str,
    body: VerifyOverallKycRequest,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> KycRecordResponse:
    emp_uuid = to_uuid(employment_id)
    await authorize_employment(session, tenant_id, scope, emp_uuid)
    if not (scope.has("kyc.verify") or scope.has("people.write")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing kyc.verify permission")

    if body.status not in (KycStatus.VERIFIED, KycStatus.REJECTED, KycStatus.ACTION_REQUIRED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    rec = await _get_or_create_record(session, tenant_id, emp_uuid)
    rec.status = body.status
    if body.status == KycStatus.VERIFIED:
        rec.verified_at = datetime.now(timezone.utc)
        rec.verified_by = user.user_account_id
        rec.rejection_reason = None
    else:
        rec.rejection_reason = body.rejection_reason
        rec.verified_at = None
        rec.verified_by = user.user_account_id

    rec.updated_at = datetime.now(timezone.utc)
    rec.updated_by = user.user_account_id
    rec.version += 1
    session.add(rec)
    await session.flush()

    return await get_employee_kyc(employment_id, tenant_id, session, scope)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a KYC document")
async def delete_document(
    document_id: str,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
) -> None:
    doc_uuid = to_uuid(document_id)
    res = await session.execute(
        select(EmployeeKycDocument)
        .where(EmployeeKycDocument.tenant_id == tenant_id)
        .where(EmployeeKycDocument.id == doc_uuid)
    )
    doc = res.scalars().first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    is_self = user.employment_id == doc.employment_id
    if is_self:
        # Employee can delete if not verified
        if doc.status == DocumentStatus.VERIFIED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete verified document. Contact HR.")
    else:
        # HR can delete
        await authorize_employment(session, tenant_id, scope, doc.employment_id)
        if not (scope.has("kyc.write") or scope.has("people.write")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission to delete document")

    # Remove file on disk if exists
    try:
        p = Path(doc.storage_path)
        if p.exists():
            p.unlink()
    except Exception:
        pass

    await session.delete(doc)
    await session.flush()


# ─── File Download & Preview ──────────────────────────────────────────────────

@router.get("/documents/{document_id}/download", summary="Download document file")
async def download_document(
    document_id: str,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
):
    return await _serve_doc_file(document_id, user, tenant_id, session, scope, inline=False)


@router.get("/documents/{document_id}/preview", summary="Preview document file inline")
async def preview_document(
    document_id: str,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
):
    return await _serve_doc_file(document_id, user, tenant_id, session, scope, inline=True)


async def _serve_doc_file(
    document_id: str,
    user: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
    scope: ScopeDep,
    inline: bool,
):
    doc_uuid = to_uuid(document_id)
    res = await session.execute(
        select(EmployeeKycDocument)
        .where(EmployeeKycDocument.tenant_id == tenant_id)
        .where(EmployeeKycDocument.id == doc_uuid)
    )
    doc = res.scalars().first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    is_self = user.employment_id == doc.employment_id
    if not is_self:
        await authorize_employment(session, tenant_id, scope, doc.employment_id)

    file_path = Path(doc.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File content not found on server")

    disp = "inline" if inline else "attachment"
    return FileResponse(
        path=str(file_path),
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.file_name,
        headers={"Content-Disposition": f'{disp}; filename="{doc.file_name}"'},
    )


# ─── Upload Helper ────────────────────────────────────────────────────────────

async def _save_uploaded_doc(
    session: SessionDep,
    tenant_id: UUID,
    employment_id: UUID,
    uploaded_by: Optional[UUID],
    file: UploadFile,
    document_type: str,
    document_title: str,
    document_number: Optional[str],
) -> KycDocumentResponse:
    storage_dir = _storage_dir_for_tenant(tenant_id)
    doc_id = uuid4()
    clean_name = _clean_filename(file.filename or f"doc_{doc_id}")
    dest_path = storage_dir / f"{doc_id}_{clean_name}"

    content = await file.read()
    file_size = len(content)

    with open(dest_path, "wb") as f:
        f.write(content)

    doc = EmployeeKycDocument(
        tenant_id=tenant_id,
        id=doc_id,
        employment_id=employment_id,
        document_type=document_type,
        document_title=document_title,
        document_number=document_number,
        file_name=clean_name,
        file_size=file_size,
        mime_type=file.content_type or "application/octet-stream",
        storage_path=str(dest_path),
        status=DocumentStatus.PENDING,
        uploaded_by=uploaded_by,
        uploaded_at=datetime.now(timezone.utc),
    )
    session.add(doc)

    # If the KYC record was NOT_SUBMITTED, update to DRAFT
    rec = await _get_or_create_record(session, tenant_id, employment_id)
    if rec.status == KycStatus.NOT_SUBMITTED:
        rec.status = KycStatus.DRAFT
        rec.updated_at = datetime.now(timezone.utc)
        session.add(rec)

    await session.flush()
    return _to_doc_response(doc)

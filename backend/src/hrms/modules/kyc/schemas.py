"""Pydantic schemas for Employee KYC API."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class KycRecordUpdateRequest(BaseModel):
    pan_number: str | None = Field(default=None, max_length=20)
    aadhaar_number: str | None = Field(default=None, max_length=20)
    uan_number: str | None = Field(default=None, max_length=20)
    pf_number: str | None = Field(default=None, max_length=50)
    esi_number: str | None = Field(default=None, max_length=50)
    passport_number: str | None = Field(default=None, max_length=50)
    passport_expiry: date | None = None
    driving_license: str | None = Field(default=None, max_length=50)
    voter_id: str | None = Field(default=None, max_length=50)

    bank_name: str | None = Field(default=None, max_length=100)
    account_holder_name: str | None = Field(default=None, max_length=255)
    account_number: str | None = Field(default=None, max_length=50)
    ifsc_code: str | None = Field(default=None, max_length=20)
    branch_name: str | None = Field(default=None, max_length=100)

    father_or_spouse_name: str | None = Field(default=None, max_length=255)
    marital_status: str | None = Field(default=None, max_length=20)
    blood_group: str | None = Field(default=None, max_length=10)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_relation: str | None = Field(default=None, max_length=50)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)
    current_address: str | None = Field(default=None, max_length=500)
    permanent_address: str | None = Field(default=None, max_length=500)


class KycDocumentResponse(BaseModel):
    id: str
    employment_id: str
    document_type: str
    document_title: str
    document_number: str | None = None
    file_name: str
    file_size: int
    mime_type: str
    status: str
    rejection_reason: str | None = None
    comments: str | None = None
    uploaded_at: datetime
    verified_at: datetime | None = None
    download_url: str
    preview_url: str


class KycRecordResponse(BaseModel):
    id: str
    employment_id: str
    employee_name: str | None = None
    employee_number: str | None = None
    department: str | None = None
    designation: str | None = None

    # Identity
    pan_number: str | None = None
    aadhaar_number: str | None = None
    uan_number: str | None = None
    pf_number: str | None = None
    esi_number: str | None = None
    passport_number: str | None = None
    passport_expiry: date | None = None
    driving_license: str | None = None
    voter_id: str | None = None

    # Bank
    bank_name: str | None = None
    account_holder_name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    branch_name: str | None = None

    # Personal & Family
    father_or_spouse_name: str | None = None
    marital_status: str | None = None
    blood_group: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_relation: str | None = None
    emergency_contact_phone: str | None = None
    current_address: str | None = None
    permanent_address: str | None = None

    # Status
    status: str
    submitted_at: datetime | None = None
    verified_at: datetime | None = None
    rejection_reason: str | None = None
    updated_at: datetime

    documents: list[KycDocumentResponse] = []
    completion_percentage: int = 0


class KycEmployeeListItem(BaseModel):
    employment_id: str
    employee_number: str
    employee_name: str
    department: str | None = None
    designation: str | None = None
    kyc_status: str
    documents_count: int = 0
    verified_documents_count: int = 0
    completion_percentage: int = 0
    updated_at: datetime | None = None


class KycSummaryStats(BaseModel):
    total_employees: int
    verified_count: int
    pending_verification_count: int
    incomplete_count: int
    rejected_count: int


class VerifyDocumentRequest(BaseModel):
    status: str = Field(description="'VERIFIED' or 'REJECTED'")
    rejection_reason: str | None = None
    comments: str | None = None


class VerifyOverallKycRequest(BaseModel):
    status: str = Field(description="'VERIFIED', 'REJECTED', or 'ACTION_REQUIRED'")
    rejection_reason: str | None = None


class KycAccessLogEntry(BaseModel):
    """One time someone other than the employee opened their KYC dossier or a document."""

    actor: str | None = None
    action: str
    unmasked: bool
    occurred_at: datetime

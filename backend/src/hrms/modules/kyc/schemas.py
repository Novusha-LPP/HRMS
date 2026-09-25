"""Pydantic schemas for Employee KYC API."""

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class KycRecordUpdateRequest(BaseModel):
    pan_number: Optional[str] = Field(default=None, max_length=20)
    aadhaar_number: Optional[str] = Field(default=None, max_length=20)
    uan_number: Optional[str] = Field(default=None, max_length=20)
    pf_number: Optional[str] = Field(default=None, max_length=50)
    esi_number: Optional[str] = Field(default=None, max_length=50)
    passport_number: Optional[str] = Field(default=None, max_length=50)
    passport_expiry: Optional[date] = None
    driving_license: Optional[str] = Field(default=None, max_length=50)
    voter_id: Optional[str] = Field(default=None, max_length=50)

    bank_name: Optional[str] = Field(default=None, max_length=100)
    account_holder_name: Optional[str] = Field(default=None, max_length=255)
    account_number: Optional[str] = Field(default=None, max_length=50)
    ifsc_code: Optional[str] = Field(default=None, max_length=20)
    branch_name: Optional[str] = Field(default=None, max_length=100)

    father_or_spouse_name: Optional[str] = Field(default=None, max_length=255)
    marital_status: Optional[str] = Field(default=None, max_length=20)
    blood_group: Optional[str] = Field(default=None, max_length=10)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=255)
    emergency_contact_relation: Optional[str] = Field(default=None, max_length=50)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=20)
    current_address: Optional[str] = Field(default=None, max_length=500)
    permanent_address: Optional[str] = Field(default=None, max_length=500)


class KycDocumentResponse(BaseModel):
    id: str
    employment_id: str
    document_type: str
    document_title: str
    document_number: Optional[str] = None
    file_name: str
    file_size: int
    mime_type: str
    status: str
    rejection_reason: Optional[str] = None
    comments: Optional[str] = None
    uploaded_at: datetime
    verified_at: Optional[datetime] = None
    download_url: str
    preview_url: str


class KycRecordResponse(BaseModel):
    id: str
    employment_id: str
    employee_name: Optional[str] = None
    employee_number: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None

    # Identity
    pan_number: Optional[str] = None
    aadhaar_number: Optional[str] = None
    uan_number: Optional[str] = None
    pf_number: Optional[str] = None
    esi_number: Optional[str] = None
    passport_number: Optional[str] = None
    passport_expiry: Optional[date] = None
    driving_license: Optional[str] = None
    voter_id: Optional[str] = None

    # Bank
    bank_name: Optional[str] = None
    account_holder_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    branch_name: Optional[str] = None

    # Personal & Family
    father_or_spouse_name: Optional[str] = None
    marital_status: Optional[str] = None
    blood_group: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    current_address: Optional[str] = None
    permanent_address: Optional[str] = None

    # Status
    status: str
    submitted_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    updated_at: datetime

    documents: list[KycDocumentResponse] = []
    completion_percentage: int = 0


class KycEmployeeListItem(BaseModel):
    employment_id: str
    employee_number: str
    employee_name: str
    department: Optional[str] = None
    designation: Optional[str] = None
    kyc_status: str
    documents_count: int = 0
    verified_documents_count: int = 0
    completion_percentage: int = 0
    updated_at: Optional[datetime] = None


class KycSummaryStats(BaseModel):
    total_employees: int
    verified_count: int
    pending_verification_count: int
    incomplete_count: int
    rejected_count: int


class VerifyDocumentRequest(BaseModel):
    status: str = Field(description="'VERIFIED' or 'REJECTED'")
    rejection_reason: Optional[str] = None
    comments: Optional[str] = None


class VerifyOverallKycRequest(BaseModel):
    status: str = Field(description="'VERIFIED', 'REJECTED', or 'ACTION_REQUIRED'")
    rejection_reason: Optional[str] = None

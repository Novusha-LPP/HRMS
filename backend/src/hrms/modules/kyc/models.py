"""Employee KYC Models: Record and Document tables with tenant isolation."""

import enum
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class KycStatus(str, enum.Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ACTION_REQUIRED = "ACTION_REQUIRED"


class DocumentType(str, enum.Enum):
    PAN_CARD = "PAN_CARD"
    AADHAAR_FRONT = "AADHAAR_FRONT"
    AADHAAR_BACK = "AADHAAR_BACK"
    BANK_PROOF = "BANK_PROOF"
    PHOTO = "PHOTO"
    ADDRESS_PROOF = "ADDRESS_PROOF"
    EDUCATION_CERT = "EDUCATION_CERT"
    EXPERIENCE_LETTER = "EXPERIENCE_LETTER"
    PAYSLIP = "PAYSLIP"
    OTHER = "OTHER"


class DocumentStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EmployeeKycRecord(SQLModel, table=True):
    __tablename__ = "employee_kyc_records"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    person_id: Optional[UUID] = Field(default=None, index=True)

    # Identity
    pan_number: Optional[str] = Field(default=None, max_length=20)
    aadhaar_number: Optional[str] = Field(default=None, max_length=20)
    uan_number: Optional[str] = Field(default=None, max_length=20)
    pf_number: Optional[str] = Field(default=None, max_length=50)
    esi_number: Optional[str] = Field(default=None, max_length=50)
    passport_number: Optional[str] = Field(default=None, max_length=50)
    passport_expiry: Optional[date] = Field(default=None)
    driving_license: Optional[str] = Field(default=None, max_length=50)
    voter_id: Optional[str] = Field(default=None, max_length=50)

    # Bank
    bank_name: Optional[str] = Field(default=None, max_length=100)
    account_holder_name: Optional[str] = Field(default=None, max_length=255)
    account_number: Optional[str] = Field(default=None, max_length=50)
    ifsc_code: Optional[str] = Field(default=None, max_length=20)
    branch_name: Optional[str] = Field(default=None, max_length=100)

    # Personal & Family
    father_or_spouse_name: Optional[str] = Field(default=None, max_length=255)
    marital_status: Optional[str] = Field(default=None, max_length=20)
    blood_group: Optional[str] = Field(default=None, max_length=10)
    emergency_contact_name: Optional[str] = Field(default=None, max_length=255)
    emergency_contact_relation: Optional[str] = Field(default=None, max_length=50)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=20)
    current_address: Optional[str] = Field(default=None, max_length=500)
    permanent_address: Optional[str] = Field(default=None, max_length=500)

    # Status & Verification
    status: str = Field(default=KycStatus.NOT_SUBMITTED, max_length=50)
    submitted_at: Optional[datetime] = Field(default=None)
    verified_at: Optional[datetime] = Field(default=None)
    verified_by: Optional[UUID] = Field(default=None)
    rejection_reason: Optional[str] = Field(default=None, max_length=1000)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: Optional[UUID] = Field(default=None)
    version: int = Field(default=0)


class EmployeeKycDocument(SQLModel, table=True):
    __tablename__ = "employee_kyc_documents"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)

    document_type: str = Field(max_length=50)
    document_title: str = Field(max_length=255)
    document_number: Optional[str] = Field(default=None, max_length=100)

    file_name: str = Field(max_length=255)
    file_size: int = Field()
    mime_type: str = Field(max_length=100)
    storage_path: str = Field(max_length=500)

    status: str = Field(default=DocumentStatus.PENDING, max_length=50)
    rejection_reason: Optional[str] = Field(default=None, max_length=1000)
    comments: Optional[str] = Field(default=None, max_length=1000)

    uploaded_by: Optional[UUID] = Field(default=None)
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verified_by: Optional[UUID] = Field(default=None)
    verified_at: Optional[datetime] = Field(default=None)
    version: int = Field(default=0)

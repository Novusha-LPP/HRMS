"""Employee KYC Models: Record and Document tables with tenant isolation."""

import enum
from datetime import UTC, date, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from hrms.core.field_crypto import EncryptedString


class KycStatus(enum.StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ACTION_REQUIRED = "ACTION_REQUIRED"


class DocumentType(enum.StrEnum):
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


class DocumentStatus(enum.StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


def _encrypted(name: str) -> sa.Column:
    """Stored encrypted at rest (core/field_crypto.py); the schemas check the length."""
    return sa.Column(name, EncryptedString(name), nullable=True)


class EmployeeKycRecord(SQLModel, table=True):
    __tablename__ = "employee_kyc_records"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)
    person_id: UUID | None = Field(default=None, index=True)

    # Identity
    pan_number: str | None = Field(default=None, sa_column=_encrypted("pan_number"))
    aadhaar_number: str | None = Field(default=None, sa_column=_encrypted("aadhaar_number"))
    uan_number: str | None = Field(default=None, sa_column=_encrypted("uan_number"))
    pf_number: str | None = Field(default=None, sa_column=_encrypted("pf_number"))
    esi_number: str | None = Field(default=None, sa_column=_encrypted("esi_number"))
    passport_number: str | None = Field(default=None, sa_column=_encrypted("passport_number"))
    passport_expiry: date | None = Field(default=None)
    driving_license: str | None = Field(default=None, sa_column=_encrypted("driving_license"))
    voter_id: str | None = Field(default=None, sa_column=_encrypted("voter_id"))

    # Bank
    bank_name: str | None = Field(default=None, max_length=100)
    account_holder_name: str | None = Field(default=None, max_length=255)
    account_number: str | None = Field(default=None, sa_column=_encrypted("account_number"))
    ifsc_code: str | None = Field(default=None, max_length=20)
    branch_name: str | None = Field(default=None, max_length=100)

    # Personal & Family
    father_or_spouse_name: str | None = Field(default=None, max_length=255)
    marital_status: str | None = Field(default=None, max_length=20)
    blood_group: str | None = Field(default=None, max_length=10)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_relation: str | None = Field(default=None, max_length=50)
    emergency_contact_phone: str | None = Field(default=None, max_length=20)
    current_address: str | None = Field(default=None, max_length=500)
    permanent_address: str | None = Field(default=None, max_length=500)

    # Status & Verification
    status: str = Field(default=KycStatus.NOT_SUBMITTED, max_length=50)
    submitted_at: datetime | None = Field(default=None)
    verified_at: datetime | None = Field(default=None)
    verified_by: UUID | None = Field(default=None)
    rejection_reason: str | None = Field(default=None, max_length=1000)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID | None = Field(default=None)
    version: int = Field(default=0)


class EmployeeKycDocument(SQLModel, table=True):
    __tablename__ = "employee_kyc_documents"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    employment_id: UUID = Field(index=True)

    document_type: str = Field(max_length=50)
    document_title: str = Field(max_length=255)
    # The identifier printed on the document (Aadhaar, PAN, …): encrypted like the record's.
    document_number: str | None = Field(default=None, sa_column=_encrypted("document_number"))

    file_name: str = Field(max_length=255)
    file_size: int = Field()
    mime_type: str = Field(max_length=100)
    storage_path: str = Field(max_length=500)

    status: str = Field(default=DocumentStatus.PENDING, max_length=50)
    rejection_reason: str | None = Field(default=None, max_length=1000)
    comments: str | None = Field(default=None, max_length=1000)

    uploaded_by: UUID | None = Field(default=None)
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    verified_by: UUID | None = Field(default=None)
    verified_at: datetime | None = Field(default=None)
    version: int = Field(default=0)


class KycAccessLog(SQLModel, table=True):
    """
    Who opened someone else's KYC dossier or documents, and whether they saw
    the identity/bank numbers unmasked. Append-only: the application role has
    INSERT and SELECT on this table, never UPDATE or DELETE (migration 0019).
    """

    __tablename__ = "kyc_access_log"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    actor_user_account_id: UUID = Field()
    employment_id: UUID = Field()
    action: str = Field(max_length=30)  # VIEW_DOSSIER | VIEW_DOCUMENT | DOWNLOAD_DOCUMENT
    unmasked: bool = Field(default=False)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

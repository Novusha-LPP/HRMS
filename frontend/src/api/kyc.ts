import { api, API_BASE_URL } from "./client";

export type KycStatus =
  | "NOT_SUBMITTED"
  | "DRAFT"
  | "SUBMITTED"
  | "VERIFIED"
  | "REJECTED"
  | "ACTION_REQUIRED";

export type DocumentStatus = "PENDING" | "VERIFIED" | "REJECTED";

export type DocumentType =
  | "PAN_CARD"
  | "AADHAAR_FRONT"
  | "AADHAAR_BACK"
  | "BANK_PROOF"
  | "PHOTO"
  | "ADDRESS_PROOF"
  | "EDUCATION_CERT"
  | "EXPERIENCE_LETTER"
  | "PAYSLIP"
  | "OTHER";

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  PAN_CARD: "PAN Card",
  AADHAAR_FRONT: "Aadhaar Card (Front)",
  AADHAAR_BACK: "Aadhaar Card (Back)",
  BANK_PROOF: "Bank Proof (Passbook / Cancelled Cheque)",
  PHOTO: "Passport Size Photograph",
  ADDRESS_PROOF: "Address Proof (Utility Bill / Agreement)",
  EDUCATION_CERT: "Highest Education Degree Certificate",
  EXPERIENCE_LETTER: "Previous Employment Relieving / Experience",
  PAYSLIP: "Previous Company Payslip",
  OTHER: "Other Supporting Document",
};

export interface KycDocument {
  id: string;
  employment_id: string;
  document_type: DocumentType;
  document_title: string;
  document_number: string | null;
  file_name: string;
  file_size: number;
  mime_type: string;
  status: DocumentStatus;
  rejection_reason: string | null;
  comments: string | null;
  uploaded_at: string;
  verified_at: string | null;
  download_url: string;
  preview_url: string;
}

export interface KycRecord {
  id: string;
  employment_id: string;
  employee_name: string | null;
  employee_number: string | null;
  department: string | null;
  designation: string | null;

  // Identity
  pan_number: string | null;
  aadhaar_number: string | null;
  uan_number: string | null;
  pf_number: string | null;
  esi_number: string | null;
  passport_number: string | null;
  passport_expiry: string | null;
  driving_license: string | null;
  voter_id: string | null;

  // Bank
  bank_name: string | null;
  account_holder_name: string | null;
  account_number: string | null;
  ifsc_code: string | null;
  branch_name: string | null;

  // Personal & Family
  father_or_spouse_name: string | null;
  marital_status: string | null;
  blood_group: string | null;
  emergency_contact_name: string | null;
  emergency_contact_relation: string | null;
  emergency_contact_phone: string | null;
  current_address: string | null;
  permanent_address: string | null;

  // Status
  status: KycStatus;
  submitted_at: string | null;
  verified_at: string | null;
  rejection_reason: string | null;
  updated_at: string;

  documents: KycDocument[];
  completion_percentage: number;
}

export interface KycEmployeeListItem {
  employment_id: string;
  employee_number: string;
  employee_name: string;
  department: string | null;
  designation: string | null;
  kyc_status: KycStatus;
  documents_count: number;
  verified_documents_count: number;
  completion_percentage: number;
  updated_at: string | null;
}

export interface KycSummaryStats {
  total_employees: number;
  verified_count: number;
  pending_verification_count: number;
  incomplete_count: number;
  rejected_count: number;
}

export interface KycRecordUpdatePayload {
  pan_number?: string | null;
  aadhaar_number?: string | null;
  uan_number?: string | null;
  pf_number?: string | null;
  esi_number?: string | null;
  passport_number?: string | null;
  passport_expiry?: string | null;
  driving_license?: string | null;
  voter_id?: string | null;
  bank_name?: string | null;
  account_holder_name?: string | null;
  account_number?: string | null;
  ifsc_code?: string | null;
  branch_name?: string | null;
  father_or_spouse_name?: string | null;
  marital_status?: string | null;
  blood_group?: string | null;
  emergency_contact_name?: string | null;
  emergency_contact_relation?: string | null;
  emergency_contact_phone?: string | null;
  current_address?: string | null;
  permanent_address?: string | null;
}

export const kycApi = {
  getMyKyc: () => api.get<KycRecord>("/v1/kyc/me"),

  updateMyKyc: (body: KycRecordUpdatePayload) => api.patch<KycRecord>("/v1/kyc/me", body),

  submitMyKyc: () => api.post<KycRecord>("/v1/kyc/me/submit", {}),

  uploadMyDocument: (
    file: File,
    documentType: string,
    documentTitle: string,
    documentNumber?: string
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("document_type", documentType);
    fd.append("document_title", documentTitle);
    if (documentNumber) fd.append("document_number", documentNumber);
    return api.postForm<KycDocument>("/v1/kyc/me/documents", fd);
  },

  getSummary: () => api.get<KycSummaryStats>("/v1/kyc/summary"),

  listEmployees: (status?: string, search?: string, limit = 100) => {
    const p = new URLSearchParams();
    if (status && status !== "ALL") p.set("status", status);
    if (search) p.set("search", search);
    p.set("limit", String(limit));
    return api.get<KycEmployeeListItem[]>(`/v1/kyc/employees?${p.toString()}`);
  },

  getEmployeeKyc: (employmentId: string) =>
    api.get<KycRecord>(`/v1/kyc/employees/${employmentId}`),

  updateEmployeeKyc: (employmentId: string, body: KycRecordUpdatePayload) =>
    api.patch<KycRecord>(`/v1/kyc/employees/${employmentId}`, body),

  uploadEmployeeDocument: (
    employmentId: string,
    file: File,
    documentType: string,
    documentTitle: string,
    documentNumber?: string
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("document_type", documentType);
    fd.append("document_title", documentTitle);
    if (documentNumber) fd.append("document_number", documentNumber);
    return api.postForm<KycDocument>(`/v1/kyc/employees/${employmentId}/documents`, fd);
  },

  verifyDocument: (
    documentId: string,
    body: { status: "VERIFIED" | "REJECTED"; rejection_reason?: string; comments?: string }
  ) => api.patch<KycDocument>(`/v1/kyc/documents/${documentId}/verify`, body),

  verifyOverallKyc: (
    employmentId: string,
    body: { status: "VERIFIED" | "REJECTED" | "ACTION_REQUIRED"; rejection_reason?: string }
  ) => api.post<KycRecord>(`/v1/kyc/employees/${employmentId}/verify`, body),

  deleteDocument: (documentId: string) =>
    api.delete(`/v1/kyc/documents/${documentId}`),

  async fetchDocumentBlob(relativeUrl: string): Promise<{ blob: Blob; url: string }> {
    const headers = { "X-HRMS-Session": "cookie" };
    const res = await fetch(`${API_BASE_URL}${relativeUrl}`, {
      headers, credentials: "include", signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) throw new Error("Failed to load document");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    return { blob, url };
  },
};

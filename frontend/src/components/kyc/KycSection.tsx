import { useState, useRef, useEffect } from "react";
import type { FormEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  FileText, Upload, Download, Eye, CheckCircle2,
  XCircle, Clock, Trash2, Check,
  FileUp, Sparkles, AlertTriangle, ShieldCheck,
  Building, Building2, RefreshCw, CreditCard,
  Users, MapPin, Copy,
} from "lucide-react";

import {
  kycApi,
  DOCUMENT_TYPE_LABELS,
  type KycDocument,
  type DocumentType,
  type KycRecordUpdatePayload,
} from "../../api/kyc";
import { StatusBadge, humanize } from "../ui/StatusBadge";
import { Dialog } from "../ui/Overlay";
import { Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"];
const MARITAL_STATUSES = ["SINGLE", "MARRIED", "DIVORCED", "WIDOWED"];

interface KycSectionProps {
  /** If true, this is the employee viewing/editing their own KYC */
  isSelf?: boolean;
  /** If provided, this is HR viewing/managing an employee's KYC */
  employmentId?: string;
  employeeName?: string;
  isHR?: boolean;
}

export function KycSection({
  isSelf = false,
  employmentId,
  employeeName,
  isHR = false,
}: KycSectionProps) {
  const qc = useQueryClient();
  const toast = useToast();

  const queryKey = isSelf ? ["my-kyc"] : ["kyc-employee", employmentId];

  // Fetch KYC record
  const kycQuery = useQuery({
    queryKey,
    queryFn: () => (isSelf ? kycApi.getMyKyc() : kycApi.getEmployeeKyc(employmentId!)),
    enabled: isSelf || !!employmentId,
  });

  const kyc = kycQuery.data;

  // Local form state for text fields
  const [form, setForm] = useState<KycRecordUpdatePayload>({});
  const [dirty, setDirty] = useState(false);
  const [prevKyc, setPrevKyc] = useState(kyc);

  if (kyc && kyc !== prevKyc && !dirty) {
    setPrevKyc(kyc);
    setForm({
      pan_number: kyc.pan_number ?? "",
      aadhaar_number: kyc.aadhaar_number ?? "",
      uan_number: kyc.uan_number ?? "",
      pf_number: kyc.pf_number ?? "",
      esi_number: kyc.esi_number ?? "",
      passport_number: kyc.passport_number ?? "",
      driving_license: kyc.driving_license ?? "",
      voter_id: kyc.voter_id ?? "",
      bank_name: kyc.bank_name ?? "",
      account_holder_name: kyc.account_holder_name ?? "",
      account_number: kyc.account_number ?? "",
      ifsc_code: kyc.ifsc_code ?? "",
      branch_name: kyc.branch_name ?? "",
      father_or_spouse_name: kyc.father_or_spouse_name ?? "",
      marital_status: kyc.marital_status ?? "",
      blood_group: kyc.blood_group ?? "",
      emergency_contact_name: kyc.emergency_contact_name ?? "",
      emergency_contact_relation: kyc.emergency_contact_relation ?? "",
      emergency_contact_phone: kyc.emergency_contact_phone ?? "",
      current_address: kyc.current_address ?? "",
      permanent_address: kyc.permanent_address ?? "",
    });
  }

  // Modals state
  const [previewDoc, setPreviewDoc] = useState<KycDocument | null>(null);
  const [uploadDocType, setUploadDocType] = useState<DocumentType | null>(null);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [verifyDocModal, setVerifyDocModal] = useState<KycDocument | null>(null);
  const [docRejectReason, setDocRejectReason] = useState("");

  // Mutations
  const saveFieldsMutation = useMutation({
    mutationFn: (payload: KycRecordUpdatePayload) =>
      isSelf
        ? kycApi.updateMyKyc(payload)
        : kycApi.updateEmployeeKyc(employmentId!, payload),
    onSuccess: (data) => {
      qc.setQueryData(queryKey, data);
      qc.invalidateQueries({ queryKey: ["kyc-employees"] });
      qc.invalidateQueries({ queryKey: ["kyc-summary"] });
      setDirty(false);
      toast.success("KYC details saved successfully");
    },
    onError: (err) => toast.error("Failed to save KYC details", errorMessage(err)),
  });

  const submitKycMutation = useMutation({
    mutationFn: () => kycApi.submitMyKyc(),
    onSuccess: (data) => {
      qc.setQueryData(queryKey, data);
      qc.invalidateQueries({ queryKey: ["kyc-employees"] });
      qc.invalidateQueries({ queryKey: ["kyc-summary"] });
      toast.success("KYC Submitted", "Your details and documents have been sent to HR for verification.");
    },
    onError: (err) => toast.error("Submission failed", errorMessage(err)),
  });

  const verifyOverallMutation = useMutation({
    mutationFn: (body: { status: "VERIFIED" | "REJECTED" | "ACTION_REQUIRED"; rejection_reason?: string }) =>
      kycApi.verifyOverallKyc(employmentId!, body),
    onSuccess: (data) => {
      qc.setQueryData(queryKey, data);
      qc.invalidateQueries({ queryKey: ["kyc-employees"] });
      qc.invalidateQueries({ queryKey: ["kyc-summary"] });
      toast.success(
        data.status === "VERIFIED"
          ? "KYC Verified Successfully"
          : "KYC Status Updated"
      );
      setRejectModalOpen(false);
    },
    onError: (err) => toast.error("Verification failed", errorMessage(err)),
  });

  const verifyDocMutation = useMutation({
    mutationFn: ({ docId, status, reason }: { docId: string; status: "VERIFIED" | "REJECTED"; reason?: string }) =>
      kycApi.verifyDocument(docId, { status, rejection_reason: reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey });
      qc.invalidateQueries({ queryKey: ["kyc-employees"] });
      toast.success("Document verification updated");
      setVerifyDocModal(null);
      setDocRejectReason("");
    },
    onError: (err) => toast.error("Failed to update document status", errorMessage(err)),
  });

  const updateField = (key: keyof KycRecordUpdatePayload, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setDirty(true);
  };

  const handleSaveFields = (e: FormEvent) => {
    e.preventDefault();
    saveFieldsMutation.mutate(form);
  };

  if (kycQuery.isPending) {
    return (
      <div className="space-y-4 py-4">
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-44 w-full rounded-2xl" />
        <Skeleton className="h-44 w-full rounded-2xl" />
      </div>
    );
  }

  if (kycQuery.isError || !kyc) {
    return (
      <div className="rounded-2xl border border-line bg-surface p-6 text-center text-danger">
        <AlertTriangle className="mx-auto h-8 w-8 text-danger mb-2" />
        <p className="font-semibold text-sm">Unable to load KYC information</p>
        <p className="text-xs text-fg-subtle mt-1">{errorMessage(kycQuery.error)}</p>
      </div>
    );
  }

  const findDoc = (type: DocumentType) => kyc.documents.find((d) => d.document_type === type);

  return (
    <div className="space-y-6">
      {/* ── Status Banner & Completion Progress ──────────────────────────── */}
      <div
        className={`rounded-2xl border p-4 sm:p-5 transition-all ${
          kyc.status === "VERIFIED"
            ? "border-emerald-500/30 bg-emerald-500/[0.04]"
            : kyc.status === "SUBMITTED"
            ? "border-blue-500/30 bg-blue-500/[0.04]"
            : kyc.status === "REJECTED" || kyc.status === "ACTION_REQUIRED"
            ? "border-rose-500/30 bg-rose-500/[0.04]"
            : "border-brand-500/30 bg-brand-500/[0.03]"
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5 min-w-0">
            <div
              className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white shadow-xs ${
                kyc.status === "VERIFIED"
                  ? "bg-emerald-600"
                  : kyc.status === "SUBMITTED"
                  ? "bg-blue-600"
                  : kyc.status === "REJECTED" || kyc.status === "ACTION_REQUIRED"
                  ? "bg-rose-600"
                  : "bg-brand-600"
              }`}
            >
              {kyc.status === "VERIFIED" ? (
                <ShieldCheck size={20} />
              ) : kyc.status === "SUBMITTED" ? (
                <Clock size={20} />
              ) : kyc.status === "REJECTED" || kyc.status === "ACTION_REQUIRED" ? (
                <AlertTriangle size={20} />
              ) : (
                <Sparkles size={20} />
              )}
            </div>

            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-sm font-semibold text-fg">
                  {employeeName ? `${employeeName} · ` : ""}
                  {kyc.status === "VERIFIED"
                    ? "KYC Verified"
                    : kyc.status === "SUBMITTED"
                    ? "KYC Submitted — Under HR Verification"
                    : kyc.status === "ACTION_REQUIRED" || kyc.status === "REJECTED"
                    ? "Action Required on KYC"
                    : "KYC Incomplete"}
                </h4>
                <StatusBadge status={kyc.status} />
              </div>

              <p className="text-xs text-fg-subtle mt-0.5">
                {kyc.status === "VERIFIED"
                  ? `Identity, statutory, and banking documents have been approved by compliance.${
                      kyc.verified_at
                        ? ` Verified on ${format(new Date(kyc.verified_at), "d MMM yyyy")}.`
                        : ""
                    }`
                  : kyc.status === "SUBMITTED"
                  ? "Your documents are under review by HR. Updates will be reflected once verified."
                  : kyc.rejection_reason
                  ? `Remarks: ${kyc.rejection_reason}`
                  : "Upload required identity proofs (Aadhaar, PAN) and banking records to verify profile."}
              </p>
            </div>
          </div>

          {/* Action buttons depending on role */}
          <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
            {isSelf && kyc.status !== "VERIFIED" && (
              <button
                type="button"
                onClick={() => submitKycMutation.mutate()}
                disabled={submitKycMutation.isPending || kyc.documents.length === 0}
                className="btn-primary btn-sm"
              >
                {submitKycMutation.isPending ? "Submitting…" : "Submit for Verification"}
              </button>
            )}

            {isHR && (
              <div className="flex items-center gap-2">
                {kyc.status !== "VERIFIED" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setRejectModalOpen(true)}
                      className="btn-danger btn-sm"
                    >
                      <XCircle size={13} /> Request Changes
                    </button>
                    <button
                      type="button"
                      onClick={() => verifyOverallMutation.mutate({ status: "VERIFIED" })}
                      disabled={verifyOverallMutation.isPending}
                      className="btn-primary btn-sm"
                    >
                      <CheckCircle2 size={13} /> Verify KYC
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => setRejectModalOpen(true)}
                    className="btn-ghost btn-sm text-xs text-fg-subtle hover:text-danger"
                  >
                    Revoke Verification
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Completion Progress Bar */}
        <div className="mt-4 border-t border-line/50 pt-3 flex items-center justify-between gap-4">
          <span className="text-[11px] font-medium text-fg-subtle">
            Completion Score ({kyc.completion_percentage}%)
          </span>
          <div className="flex items-center gap-2 w-48">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
              <div
                className={`h-full transition-all duration-300 ${
                  kyc.completion_percentage === 100
                    ? "bg-emerald-500"
                    : kyc.completion_percentage >= 50
                    ? "bg-amber-500"
                    : "bg-brand-500"
                }`}
                style={{ width: `${kyc.completion_percentage}%` }}
              />
            </div>
            <span className="text-[11px] font-mono font-bold text-fg">
              {kyc.completion_percentage}%
            </span>
          </div>
        </div>
      </div>

      <form onSubmit={handleSaveFields} className="space-y-6">
        {/* ── 1. STATUTORY TAX & NATIONAL IDENTITY (PAN & AADHAAR) ──────── */}
        <div className="card p-5 space-y-5">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <div className="flex items-center gap-2.5">
              <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500/10 text-brand-500">
                <CreditCard size={15} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-fg">Statutory Tax & National Identity</h4>
                <p className="text-xs text-fg-subtle">Mandatory tax and identity proofs required for legal onboarding</p>
              </div>
            </div>
          </div>

          {/* Row 1: PAN Number + PAN Card Document */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">
                  PAN Number <span className="text-danger">*</span>
                </label>
              </div>
              <input
                type="text"
                maxLength={10}
                placeholder="ABCDE1234F"
                value={form.pan_number ?? ""}
                onChange={(e) => updateField("pan_number", e.target.value.toUpperCase())}
                className="input font-mono uppercase tracking-wider text-sm h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">10-character alphanumeric income tax identifier</p>
            </div>

            <DocumentSlot
              docType="PAN_CARD"
              label="PAN Card Document"
              required
              hint="Clear scan or photo of PAN card (PDF, PNG, JPG)"
              document={findDoc("PAN_CARD")}
              onUpload={() => setUploadDocType("PAN_CARD")}
              onPreview={(doc) => setPreviewDoc(doc)}
              isHR={isHR}
              onVerify={(docId) => verifyDocMutation.mutate({ docId, status: "VERIFIED" })}
              onReject={(doc) => setVerifyDocModal(doc)}
              canDelete={isHR || kyc.status !== "VERIFIED"}
              queryKey={queryKey}
            />
          </div>

          {/* Row 2: Aadhaar Number + Aadhaar Front Document */}
          <div className="border-t border-line/60 pt-4 grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">
                  Aadhaar Number <span className="text-danger">*</span>
                </label>
              </div>
              <input
                type="text"
                maxLength={12}
                placeholder="123456789012"
                value={form.aadhaar_number ?? ""}
                onChange={(e) => updateField("aadhaar_number", e.target.value.replace(/\D/g, ""))}
                className="input font-mono text-sm h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">12-digit UIDAI unique identification number</p>
            </div>

            <DocumentSlot
              docType="AADHAAR_FRONT"
              label="Aadhaar Card (Front / e-Aadhaar)"
              required
              hint="Front page with photo or full e-Aadhaar PDF copy"
              document={findDoc("AADHAAR_FRONT")}
              onUpload={() => setUploadDocType("AADHAAR_FRONT")}
              onPreview={(doc) => setPreviewDoc(doc)}
              isHR={isHR}
              onVerify={(docId) => verifyDocMutation.mutate({ docId, status: "VERIFIED" })}
              onReject={(doc) => setVerifyDocModal(doc)}
              canDelete={isHR || kyc.status !== "VERIFIED"}
              queryKey={queryKey}
            />
          </div>
        </div>

        {/* ── 2. BANK ACCOUNT & DIRECT SALARY DEPOSIT ────────────────────── */}
        <div className="card p-5 space-y-5">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <div className="flex items-center gap-2.5">
              <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500/10 text-brand-500">
                <Building size={15} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-fg">Bank Account & Direct Salary Deposit</h4>
                <p className="text-xs text-fg-subtle">Designated salary bank account with verified passbook or cheque proof</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
            {/* Left Column: Bank Name & Branch */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col">
                <div className="flex items-center justify-between mb-1.5 h-5">
                  <label className="text-xs font-medium text-fg-muted truncate">
                    Bank Name <span className="text-danger">*</span>
                  </label>
                </div>
                <input
                  type="text"
                  placeholder="e.g. HDFC Bank, SBI"
                  value={form.bank_name ?? ""}
                  onChange={(e) => updateField("bank_name", e.target.value)}
                  className="input text-xs h-9"
                />
                <p className="text-[11px] text-fg-subtle mt-1">Bank organization</p>
              </div>

              <div className="flex flex-col">
                <div className="flex items-center justify-between mb-1.5 h-5">
                  <label className="text-xs font-medium text-fg-muted truncate">Branch Name</label>
                </div>
                <input
                  type="text"
                  placeholder="Branch location"
                  value={form.branch_name ?? ""}
                  onChange={(e) => updateField("branch_name", e.target.value)}
                  className="input text-xs h-9"
                />
                <p className="text-[11px] text-fg-subtle mt-1">Branch / City</p>
              </div>
            </div>

            {/* Right Column: Account Number & IFSC Code */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col">
                <div className="flex items-center justify-between mb-1.5 h-5">
                  <label className="text-xs font-medium text-fg-muted truncate">
                    Account Number <span className="text-danger">*</span>
                  </label>
                </div>
                <input
                  type="text"
                  placeholder="Account number"
                  value={form.account_number ?? ""}
                  onChange={(e) => updateField("account_number", e.target.value.replace(/\s/g, ""))}
                  className="input font-mono text-xs h-9"
                />
                <p className="text-[11px] text-fg-subtle mt-1">Savings or salary A/C</p>
              </div>

              <div className="flex flex-col">
                <div className="flex items-center justify-between mb-1.5 h-5">
                  <label className="text-xs font-medium text-fg-muted truncate">
                    IFSC Code <span className="text-danger">*</span>
                  </label>
                </div>
                <input
                  type="text"
                  maxLength={11}
                  placeholder="e.g. HDFC0000123"
                  value={form.ifsc_code ?? ""}
                  onChange={(e) => updateField("ifsc_code", e.target.value.toUpperCase())}
                  className="input font-mono uppercase text-xs h-9"
                />
                <p className="text-[11px] text-fg-subtle mt-1">11-character code</p>
              </div>
            </div>
          </div>

          {/* Sub-row: Account Holder Name + Bank Proof Upload */}
          <div className="border-t border-line/60 pt-4 grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">
                  Account Holder Name <span className="text-danger">*</span>
                </label>
              </div>
              <input
                type="text"
                placeholder="Exact name as in bank records"
                value={form.account_holder_name ?? ""}
                onChange={(e) => updateField("account_holder_name", e.target.value)}
                className="input text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Must match employee legal name</p>
            </div>

            <DocumentSlot
              docType="BANK_PROOF"
              label="Bank Proof (Passbook / Cancelled Cheque)"
              required
              hint="Passbook first page or cancelled cheque showing A/C and IFSC"
              document={findDoc("BANK_PROOF")}
              onUpload={() => setUploadDocType("BANK_PROOF")}
              onPreview={(doc) => setPreviewDoc(doc)}
              isHR={isHR}
              onVerify={(docId) => verifyDocMutation.mutate({ docId, status: "VERIFIED" })}
              onReject={(doc) => setVerifyDocModal(doc)}
              canDelete={isHR || kyc.status !== "VERIFIED"}
              queryKey={queryKey}
            />
          </div>
        </div>

        {/* ── 3. PROVIDENT FUND (PF) & STATUTORY IDENTIFIERS ─────────────── */}
        <div className="card p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <div className="flex items-center gap-2.5">
              <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500/10 text-brand-500">
                <Building2 size={15} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-fg">Statutory Provident Fund & Identity Numbers</h4>
                <p className="text-xs text-fg-subtle">Social security registrations and optional secondary identity identifiers</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 items-start">
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">UAN Number (PF)</label>
              </div>
              <input
                type="text"
                maxLength={12}
                placeholder="12-digit UAN"
                value={form.uan_number ?? ""}
                onChange={(e) => updateField("uan_number", e.target.value.replace(/\D/g, ""))}
                className="input font-mono text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Universal Account Number</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">PF Member ID</label>
              </div>
              <input
                type="text"
                placeholder="e.g. MH/BAN/12345/678"
                value={form.pf_number ?? ""}
                onChange={(e) => updateField("pf_number", e.target.value.toUpperCase())}
                className="input font-mono uppercase text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Previous or current PF ID</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">ESI Number</label>
              </div>
              <input
                type="text"
                maxLength={17}
                placeholder="17-digit ESI number"
                value={form.esi_number ?? ""}
                onChange={(e) => updateField("esi_number", e.target.value.replace(/\D/g, ""))}
                className="input font-mono text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">State Insurance registration</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Passport Number</label>
              </div>
              <input
                type="text"
                placeholder="Passport number"
                value={form.passport_number ?? ""}
                onChange={(e) => updateField("passport_number", e.target.value.toUpperCase())}
                className="input font-mono uppercase text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">For travel & compliance</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Driving License</label>
              </div>
              <input
                type="text"
                placeholder="Driving license number"
                value={form.driving_license ?? ""}
                onChange={(e) => updateField("driving_license", e.target.value.toUpperCase())}
                className="input font-mono uppercase text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Secondary identity proof</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Voter ID (EPIC)</label>
              </div>
              <input
                type="text"
                placeholder="Voter ID number"
                value={form.voter_id ?? ""}
                onChange={(e) => updateField("voter_id", e.target.value.toUpperCase())}
                className="input font-mono uppercase text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Election commission identifier</p>
            </div>
          </div>
        </div>

        {/* ── 4. REQUIRED CREDENTIALS & SUPPORTING DOCUMENTS ────────────── */}
        <div className="card p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <div className="flex items-center gap-2.5">
              <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500/10 text-brand-500">
                <FileText size={15} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-fg">Supporting Credentials & Documents</h4>
                <p className="text-xs text-fg-subtle">Formal photograph, education degree, and previous employment service letter</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
            <DocumentSlot
              docType="PHOTO"
              label="Profile Photograph"
              required
              hint="Formal passport-style photo with plain background"
              document={findDoc("PHOTO")}
              onUpload={() => setUploadDocType("PHOTO")}
              onPreview={(doc) => setPreviewDoc(doc)}
              isHR={isHR}
              onVerify={(docId) => verifyDocMutation.mutate({ docId, status: "VERIFIED" })}
              onReject={(doc) => setVerifyDocModal(doc)}
              canDelete={isHR || kyc.status !== "VERIFIED"}
              queryKey={queryKey}
            />

            <DocumentSlot
              docType="EDUCATION_CERT"
              label="Highest Education Degree / Marksheet"
              required
              hint="Degree certificate or final semester marksheet"
              document={findDoc("EDUCATION_CERT")}
              onUpload={() => setUploadDocType("EDUCATION_CERT")}
              onPreview={(doc) => setPreviewDoc(doc)}
              isHR={isHR}
              onVerify={(docId) => verifyDocMutation.mutate({ docId, status: "VERIFIED" })}
              onReject={(doc) => setVerifyDocModal(doc)}
              canDelete={isHR || kyc.status !== "VERIFIED"}
              queryKey={queryKey}
            />

            <DocumentSlot
              docType="EXPERIENCE_LETTER"
              label="Previous Relieving / Service Letter"
              hint="Relieving letter or experience certificate from last employer"
              document={findDoc("EXPERIENCE_LETTER")}
              onUpload={() => setUploadDocType("EXPERIENCE_LETTER")}
              onPreview={(doc) => setPreviewDoc(doc)}
              isHR={isHR}
              onVerify={(docId) => verifyDocMutation.mutate({ docId, status: "VERIFIED" })}
              onReject={(doc) => setVerifyDocModal(doc)}
              canDelete={isHR || kyc.status !== "VERIFIED"}
              queryKey={queryKey}
            />

            <DocumentSlot
              docType="ADDRESS_PROOF"
              label="Permanent Address Proof"
              hint="Electricity bill, rental agreement, or passport copy"
              document={findDoc("ADDRESS_PROOF")}
              onUpload={() => setUploadDocType("ADDRESS_PROOF")}
              onPreview={(doc) => setPreviewDoc(doc)}
              isHR={isHR}
              onVerify={(docId) => verifyDocMutation.mutate({ docId, status: "VERIFIED" })}
              onReject={(doc) => setVerifyDocModal(doc)}
              canDelete={isHR || kyc.status !== "VERIFIED"}
              queryKey={queryKey}
            />
          </div>
        </div>

        {/* ── 5. PERSONAL, FAMILY & EMERGENCY CONTACTS ───────────────────── */}
        <div className="card p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <div className="flex items-center gap-2.5">
              <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500/10 text-brand-500">
                <Users size={15} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-fg">Family & Emergency Contacts</h4>
                <p className="text-xs text-fg-subtle">Family records for statutory nominee records and emergency contacts</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 items-start">
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Father's / Spouse's Name</label>
              </div>
              <input
                type="text"
                placeholder="Full name"
                value={form.father_or_spouse_name ?? ""}
                onChange={(e) => updateField("father_or_spouse_name", e.target.value)}
                className="input text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">As per statutory records</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Marital Status</label>
              </div>
              <select
                value={form.marital_status ?? ""}
                onChange={(e) => updateField("marital_status", e.target.value)}
                className="input text-xs h-9"
              >
                <option value="">Select status</option>
                {MARITAL_STATUSES.map((m) => (
                  <option key={m} value={m}>
                    {humanize(m)}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-fg-subtle mt-1">Marital status</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Blood Group</label>
              </div>
              <select
                value={form.blood_group ?? ""}
                onChange={(e) => updateField("blood_group", e.target.value)}
                className="input text-xs h-9"
              >
                <option value="">Select blood group</option>
                {BLOOD_GROUPS.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-fg-subtle mt-1">Medical records</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Emergency Contact Name</label>
              </div>
              <input
                type="text"
                placeholder="Contact person"
                value={form.emergency_contact_name ?? ""}
                onChange={(e) => updateField("emergency_contact_name", e.target.value)}
                className="input text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Emergency contact person</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Relationship</label>
              </div>
              <input
                type="text"
                placeholder="e.g. Spouse, Father, Mother"
                value={form.emergency_contact_relation ?? ""}
                onChange={(e) => updateField("emergency_contact_relation", e.target.value)}
                className="input text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Relation to employee</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Emergency Phone</label>
              </div>
              <input
                type="tel"
                placeholder="+91 98765 43210"
                value={form.emergency_contact_phone ?? ""}
                onChange={(e) => updateField("emergency_contact_phone", e.target.value)}
                className="input text-xs h-9"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Direct contact mobile number</p>
            </div>
          </div>
        </div>

        {/* ── 6. RESIDENTIAL ADDRESSES ───────────────────────────────────── */}
        <div className="card p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <div className="flex items-center gap-2.5">
              <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500/10 text-brand-500">
                <MapPin size={15} />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-fg">Residential Addresses</h4>
                <p className="text-xs text-fg-subtle">Current residing address and permanent hometown address</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 items-start">
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Current Residential Address</label>
              </div>
              <textarea
                rows={3}
                placeholder="House/flat number, street, city, state, pin code"
                value={form.current_address ?? ""}
                onChange={(e) => updateField("current_address", e.target.value)}
                className="input text-xs py-2 leading-relaxed"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Current residing location</p>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-1.5 h-5">
                <label className="text-xs font-medium text-fg-muted">Permanent Address</label>
                <button
                  type="button"
                  onClick={() => {
                    if (form.current_address) {
                      updateField("permanent_address", form.current_address);
                      toast.info("Copied current address to permanent address");
                    }
                  }}
                  className="text-[11px] text-brand-500 hover:text-brand-600 font-medium inline-flex items-center gap-1"
                >
                  <Copy size={11} /> Same as current
                </button>
              </div>
              <textarea
                rows={3}
                placeholder="Hometown address, district, state, pin code"
                value={form.permanent_address ?? ""}
                onChange={(e) => updateField("permanent_address", e.target.value)}
                className="input text-xs py-2 leading-relaxed"
              />
              <p className="text-[11px] text-fg-subtle mt-1">Permanent hometown address as per government ID</p>
            </div>
          </div>
        </div>

        {/* ── Sticky Save Changes Bar ────────────────────────────────────── */}
        <div className="sticky bottom-3 z-10 flex items-center justify-between rounded-xl border border-line bg-surface/95 backdrop-blur-md p-3.5 shadow-pop">
          <span className="text-xs text-fg-subtle">
            {dirty ? "You have unsaved changes in the fields above." : "All details are saved."}
          </span>
          <div className="flex items-center gap-2">
            {dirty && (
              <button
                type="button"
                onClick={() => {
                  setForm({
                    pan_number: kyc.pan_number ?? "",
                    aadhaar_number: kyc.aadhaar_number ?? "",
                    uan_number: kyc.uan_number ?? "",
                    bank_name: kyc.bank_name ?? "",
                    account_number: kyc.account_number ?? "",
                    ifsc_code: kyc.ifsc_code ?? "",
                    father_or_spouse_name: kyc.father_or_spouse_name ?? "",
                    emergency_contact_name: kyc.emergency_contact_name ?? "",
                    emergency_contact_phone: kyc.emergency_contact_phone ?? "",
                    current_address: kyc.current_address ?? "",
                    permanent_address: kyc.permanent_address ?? "",
                  });
                  setDirty(false);
                }}
                className="btn-ghost btn-sm text-xs"
              >
                Discard
              </button>
            )}
            <button
              type="submit"
              disabled={!dirty || saveFieldsMutation.isPending}
              className="btn-primary btn-sm"
            >
              {saveFieldsMutation.isPending ? "Saving…" : "Save Details"}
            </button>
          </div>
        </div>
      </form>

      {/* Upload Document Modal */}
      {uploadDocType && (
        <UploadDocumentDialog
          employmentId={employmentId}
          presetType={uploadDocType}
          isHR={isHR}
          onClose={() => setUploadDocType(null)}
          onSuccess={() => {
            setUploadDocType(null);
            qc.invalidateQueries({ queryKey });
            qc.invalidateQueries({ queryKey: ["kyc-employees"] });
          }}
        />
      )}

      {/* Document Preview Modal */}
      {previewDoc && (
        <DocumentPreviewDialog
          doc={previewDoc}
          onClose={() => setPreviewDoc(null)}
        />
      )}

      {/* Overall Reject Dialog */}
      {rejectModalOpen && (
        <Dialog open={true} onClose={() => setRejectModalOpen(false)}>
          <div className="p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-rose-500/10 text-rose-500">
                <AlertTriangle size={20} />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-fg">Request KYC Corrections</h3>
                <p className="text-xs text-fg-subtle">
                  Specify what information or document needs to be corrected by the employee.
                </p>
              </div>
            </div>

            <textarea
              className="input w-full min-h-[90px] text-xs py-2"
              placeholder="e.g. Please provide a clear scan of Aadhaar Card and updated passbook."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-line">
              <button
                type="button"
                onClick={() => setRejectModalOpen(false)}
                className="btn-secondary btn-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() =>
                  verifyOverallMutation.mutate({
                    status: "ACTION_REQUIRED",
                    rejection_reason:
                      rejectReason.trim() || "Documents or details require correction",
                  })
                }
                disabled={verifyOverallMutation.isPending}
                className="btn-danger btn-sm"
              >
                {verifyOverallMutation.isPending ? "Sending…" : "Send to Employee"}
              </button>
            </div>
          </div>
        </Dialog>
      )}

      {/* Individual Document Reject Dialog */}
      {verifyDocModal && (
        <Dialog open={true} onClose={() => setVerifyDocModal(null)}>
          <div className="p-6 space-y-4">
            <h3 className="text-sm font-semibold text-fg">
              Reject Document: {verifyDocModal.document_title}
            </h3>
            <p className="text-xs text-fg-subtle">
              Provide feedback for the employee on why this document is rejected.
            </p>
            <input
              type="text"
              className="input text-xs"
              placeholder="e.g. Document copy is blurry or unreadable"
              value={docRejectReason}
              onChange={(e) => setDocRejectReason(e.target.value)}
            />
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-line">
              <button
                type="button"
                onClick={() => setVerifyDocModal(null)}
                className="btn-secondary btn-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() =>
                  verifyDocMutation.mutate({
                    docId: verifyDocModal.id,
                    status: "REJECTED",
                    reason:
                      docRejectReason.trim() ||
                      "Document does not meet verification requirements",
                  })
                }
                className="btn-danger btn-sm"
              >
                Reject Document
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPACT FIELD-ATTACHED DOCUMENT SLOT (100% HORIZONTALLY & VERTICALLY ALIGNED)
// ─────────────────────────────────────────────────────────────────────────────

function DocumentSlot({
  docType,
  label,
  required = false,
  hint,
  document,
  onUpload,
  onPreview,
  isHR,
  onVerify,
  onReject,
  canDelete = true,
  queryKey,
}: {
  docType: DocumentType;
  label: string;
  required?: boolean;
  hint?: string;
  document?: KycDocument;
  onUpload: () => void;
  onPreview: (doc: KycDocument) => void;
  isHR: boolean;
  onVerify: (id: string) => void;
  onReject: (doc: KycDocument) => void;
  canDelete?: boolean;
  queryKey: unknown[];
}) {
  const qc = useQueryClient();
  const toast = useToast();

  const deleteMutation = useMutation({
    mutationFn: (id: string) => kycApi.deleteDocument(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey });
      toast.success("Document removed");
    },
    onError: (err) => toast.error("Could not remove document", errorMessage(err)),
  });

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between mb-1.5 h-5">
        <label className="text-xs font-medium text-fg-muted truncate">
          {label} {required && <span className="text-danger">*</span>}
        </label>
        {document && <StatusBadge status={document.status} />}
      </div>

      <div
        className={`flex h-9 w-full items-center justify-between gap-2 rounded-lg border px-3 text-xs transition-colors ${
          document
            ? document.status === "VERIFIED"
              ? "border-emerald-500/40 bg-emerald-500/[0.03]"
              : document.status === "REJECTED"
              ? "border-rose-500/40 bg-rose-500/[0.03]"
              : "border-line bg-surface"
            : "border-dashed border-line bg-surface/50 hover:border-brand-500/60 hover:bg-brand-500/[0.02] cursor-pointer"
        }`}
        onClick={document ? undefined : onUpload}
      >
        {document ? (
          <>
            <div className="flex items-center gap-2 min-w-0">
              <FileText
                size={14}
                className={`shrink-0 ${
                  document.status === "VERIFIED"
                    ? "text-emerald-500"
                    : document.status === "REJECTED"
                    ? "text-rose-500"
                    : "text-brand-500"
                }`}
              />
              <span className="truncate font-medium text-fg text-xs" title={document.file_name}>
                {document.file_name}
              </span>
              <span className="shrink-0 text-[10px] text-fg-subtle font-mono">
                ({(document.file_size / 1024).toFixed(0)} KB)
              </span>
            </div>

            <div className="flex items-center gap-0.5 shrink-0">
              <button
                type="button"
                onClick={() => onPreview(document)}
                className="btn-ghost btn-sm h-7 px-1.5 text-xs"
                title="Preview document"
              >
                <Eye size={12} />
              </button>
              <DocumentDownload document={document}
                className="btn-ghost btn-sm h-7 px-1.5 text-xs"
                title="Download file"
              >
                <Download size={12} />
              </DocumentDownload>

              {isHR && document.status !== "VERIFIED" && (
                <button
                  type="button"
                  onClick={() => onVerify(document.id)}
                  className="btn-ghost btn-sm h-7 px-2 text-[11px] text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10 font-medium"
                  title="Approve document"
                >
                  <Check size={12} /> Approve
                </button>
              )}
              {isHR && document.status !== "REJECTED" && (
                <button
                  type="button"
                  onClick={() => onReject(document)}
                  className="btn-ghost btn-sm h-7 px-2 text-[11px] text-rose-600 dark:text-rose-400 hover:bg-rose-500/10 font-medium"
                  title="Reject document"
                >
                  <XCircle size={12} /> Reject
                </button>
              )}

              {canDelete && document.status !== "VERIFIED" && (
                <>
                  <button
                    type="button"
                    onClick={onUpload}
                    className="btn-ghost btn-sm h-7 px-1.5 text-brand-500"
                    title="Replace file"
                  >
                    <RefreshCw size={11} />
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteMutation.mutate(document.id)}
                    className="btn-icon h-7 w-7 text-fg-subtle hover:text-danger"
                    title="Remove file"
                  >
                    <Trash2 size={12} />
                  </button>
                </>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2 min-w-0">
              <Upload size={13} className="text-brand-500 shrink-0" />
              <span className="truncate text-fg-subtle">
                Upload {DOCUMENT_TYPE_LABELS[docType] || label}
              </span>
            </div>
            <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
              Attach
            </span>
          </>
        )}
      </div>

      {document?.status === "REJECTED" && document.rejection_reason ? (
        <p className="text-[11px] text-rose-600 dark:text-rose-400 font-medium mt-1">
          Rejected: {document.rejection_reason}
        </p>
      ) : hint ? (
        <p className="text-[11px] text-fg-subtle mt-1">{hint}</p>
      ) : (
        <p className="text-[11px] text-transparent mt-1 select-none pointer-events-none">—</p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DIALOGS: UPLOAD & PREVIEW
// ─────────────────────────────────────────────────────────────────────────────

function UploadDocumentDialog({
  employmentId,
  presetType,
  isHR,
  onClose,
  onSuccess,
}: {
  employmentId?: string;
  presetType: DocumentType;
  isHR: boolean;
  onClose: () => void;
  onSuccess: () => void;
  }) {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [docNumber, setDocNumber] = useState("");
  const [uploading, setUploading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) {
      toast.error("Please select a file to upload");
      return;
    }

    setUploading(true);
    try {
      if (isHR && employmentId) {
        await kycApi.uploadEmployeeDocument(
          employmentId,
          file,
          presetType,
          DOCUMENT_TYPE_LABELS[presetType],
          docNumber.trim() || undefined
        );
      } else {
        await kycApi.uploadMyDocument(
          file,
          presetType,
          DOCUMENT_TYPE_LABELS[presetType],
          docNumber.trim() || undefined
        );
      }
      toast.success("Document attached successfully");
      onSuccess();
    } catch (err) {
      toast.error("Upload failed", errorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Dialog open={true} onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/10 text-brand-500">
            <Upload size={20} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-fg">
              Upload {DOCUMENT_TYPE_LABELS[presetType]}
            </h3>
            <p className="text-xs text-fg-subtle">
              PDF, PNG, or JPG (up to 15MB)
            </p>
          </div>
        </div>

        <div>
          <label className="label">
            Reference / Document Number{" "}
            <span className="text-fg-subtle font-normal">(Optional)</span>
          </label>
          <input
            type="text"
            placeholder="e.g. Number on card/certificate"
            value={docNumber}
            onChange={(e) => setDocNumber(e.target.value)}
            className="input text-xs font-mono"
          />
        </div>

        <div>
          <label className="label">Select File</label>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg"
            onChange={(e) => {
              if (e.target.files && e.target.files[0]) {
                setFile(e.target.files[0]);
              }
            }}
            className="hidden"
          />

          <div
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors ${
              file
                ? "border-brand-500 bg-brand-500/[0.04]"
                : "border-line hover:border-brand-500/50 bg-canvas"
            }`}
          >
            <FileUp className="mx-auto h-7 w-7 text-brand-500 mb-1.5" />
            {file ? (
              <div className="text-xs">
                <p className="font-semibold text-fg truncate">{file.name}</p>
                <p className="text-fg-subtle mt-0.5">
                  {(file.size / 1024).toFixed(0)} KB · Click to change
                </p>
              </div>
            ) : (
              <div className="text-xs text-fg-subtle">
                <span className="font-semibold text-brand-500">Choose file</span> or drag & drop
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-line">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">
            Cancel
          </button>
          <button
            type="submit"
            disabled={!file || uploading}
            className="btn-primary btn-sm"
          >
            {uploading ? "Uploading…" : "Attach Document"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function DocumentPreviewDialog({
  doc,
  onClose,
}: {
  doc: KycDocument;
  onClose: () => void;
}) {
  const isImage = doc.mime_type.startsWith("image/");
  const [preview, setPreview] = useState<{ url?: string; error?: string }>({});
  useEffect(() => {
    let active = true;
    let objectUrl: string | undefined;
    kycApi.fetchDocumentBlob(doc.preview_url).then(({ url }) => {
      objectUrl = url;
      if (active) setPreview({ url });
      else URL.revokeObjectURL(url);
    }).catch(() => { if (active) setPreview({ error: "Could not load document" }); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [doc.preview_url]);

  return (
    <Dialog open={true} onClose={onClose} className="max-w-2xl">
      <div className="p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">{doc.document_title}</h3>
            <p className="text-xs text-fg-subtle">
              {doc.file_name} · {(doc.file_size / 1024).toFixed(0)} KB · Uploaded{" "}
              {format(new Date(doc.uploaded_at), "d MMM yyyy, h:mm a")}
            </p>
          </div>
          <StatusBadge status={doc.status} />
        </div>

        <div className="max-h-[60vh] overflow-auto rounded-xl border border-line bg-canvas p-2 flex items-center justify-center">
          {preview.error ? <p role="alert">{preview.error}</p> : !preview.url ? <p>Loading document…</p> : isImage ? (
            <img
              src={preview.url}
              alt={doc.document_title}
              className="max-h-[55vh] max-w-full rounded-lg object-contain"
            />
          ) : (
            <iframe
              sandbox=""
              src={preview.url}
              title={doc.document_title}
              className="h-[55vh] w-full rounded-lg border-0"
            />
          )}
        </div>

        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-fg-subtle">
            {doc.document_number ? `Doc Ref: ${doc.document_number}` : ""}
          </span>
          <div className="flex items-center gap-2">
            <DocumentDownload document={doc}
              className="btn-secondary btn-sm"
            >
              <Download size={13} /> Download
            </DocumentDownload>
            <button
              type="button"
              onClick={onClose}
              className="btn-primary btn-sm"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}


function DocumentDownload({ document, children, ...props }: {
  document: KycDocument; children: React.ReactNode; className?: string; title?: string;
}) {
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true); setError(false);
    try {
      const { url } = await kycApi.fetchDocumentBlob(document.download_url);
      const link = window.document.createElement("a");
      link.href = url; link.download = document.file_name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <><button type="button" {...props} onClick={download} disabled={busy}>{children}</button>
    {error && <span role="alert">Download failed. Try again.</span>}</>;
}

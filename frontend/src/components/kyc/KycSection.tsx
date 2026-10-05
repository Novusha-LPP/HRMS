import { useState, useRef, useEffect } from "react";
import type { DragEvent, FormEvent, ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  FileText, Upload, Download, Eye, EyeOff, CheckCircle2, XCircle, Clock, Trash2, Check,
  FileUp, Sparkles, AlertTriangle, ShieldCheck, Building, Building2, RefreshCw,
  CreditCard, Users, MapPin, Copy, FolderOpen, ImageIcon, X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  kycApi,
  DOCUMENT_TYPE_LABELS,
  type KycDocument,
  type KycRecord,
  type KycStatus,
  type DocumentType,
  type KycRecordUpdatePayload,
} from "../../api/kyc";
import { useAuth } from "../../context/AuthContext";
import { StatusBadge, humanize } from "../ui/StatusBadge";
import { ConfirmDialog, Dialog } from "../ui/Overlay";
import { Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { DetailGrid, DetailItem, EditableSection, EmptyValue, FieldGrid } from "../ui/EditableSection";

const MAX_UPLOAD_MB = 10;
const PREVIEWABLE = new Set(["application/pdf", "image/png", "image/jpeg"]);

// ─── Field definitions ──────────────────────────────────────────────────────

type FieldKey = Exclude<keyof KycRecordUpdatePayload, "passport_expiry">;

interface FieldDef {
  key: FieldKey;
  label: string;
  required?: boolean;
  placeholder?: string;
  hint?: string;
  type?: "text" | "tel" | "select" | "textarea";
  options?: { value: string; label: string }[];
  maxLength?: number;
  mono?: boolean;
  /** Applied to every keystroke (upper-casing, stripping spaces…). */
  normalize?: (v: string) => string;
  /** Masked in view mode until revealed. */
  sensitive?: boolean;
  display?: (v: string) => string;
}

type SectionId = "identity" | "bank" | "statutory" | "family" | "address";

interface SectionDef {
  id: SectionId;
  title: string;
  description: string;
  icon: LucideIcon;
  fields: FieldDef[];
  min?: number;
}

const upper = (v: string) => v.toUpperCase();
const digits = (v: string) => v.replace(/\D/g, "");
const noSpaces = (v: string) => v.replace(/\s/g, "");
const group4 = (v: string) => v.replace(/(\d{4})(?=\d)/g, "$1 ");

const SECTIONS: SectionDef[] = [
  {
    id: "identity",
    title: "Identity & tax",
    description: "Government-issued identifiers used for statutory compliance",
    icon: CreditCard,
    fields: [
      { key: "pan_number", label: "PAN", required: true, placeholder: "ABCDE1234F", hint: "10 characters", maxLength: 10, mono: true, normalize: (v) => upper(noSpaces(v)) },
      { key: "aadhaar_number", label: "Aadhaar number", required: true, placeholder: "1234 5678 9012", hint: "12 digits", maxLength: 12, mono: true, normalize: digits, sensitive: true, display: group4 },
      { key: "passport_number", label: "Passport number", placeholder: "Optional", mono: true, maxLength: 50, normalize: upper },
      { key: "driving_license", label: "Driving licence", placeholder: "Optional", mono: true, maxLength: 50, normalize: upper },
      { key: "voter_id", label: "Voter ID (EPIC)", placeholder: "Optional", mono: true, maxLength: 50, normalize: upper },
    ],
  },
  {
    id: "bank",
    title: "Bank account",
    description: "Salary is credited to this account",
    icon: Building,
    fields: [
      { key: "account_holder_name", label: "Account holder name", placeholder: "As printed on the passbook", maxLength: 255 },
      { key: "bank_name", label: "Bank name", required: true, placeholder: "e.g. HDFC Bank", maxLength: 100 },
      { key: "account_number", label: "Account number", required: true, placeholder: "Account number", mono: true, maxLength: 50, normalize: noSpaces, sensitive: true },
      { key: "ifsc_code", label: "IFSC code", required: true, placeholder: "HDFC0000123", hint: "11 characters", mono: true, maxLength: 11, normalize: (v) => upper(noSpaces(v)) },
      { key: "branch_name", label: "Branch", placeholder: "Branch / city", maxLength: 100 },
    ],
  },
  {
    id: "statutory",
    title: "Provident fund & ESI",
    description: "Social-security registrations, if you have them",
    icon: Building2,
    fields: [
      { key: "uan_number", label: "UAN", placeholder: "12-digit UAN", maxLength: 12, mono: true, normalize: digits },
      { key: "pf_number", label: "PF member ID", placeholder: "e.g. MH/BAN/12345/678", maxLength: 50, mono: true, normalize: upper },
      { key: "esi_number", label: "ESI number", placeholder: "17-digit ESI number", maxLength: 17, mono: true, normalize: digits },
    ],
  },
  {
    id: "family",
    title: "Family & emergency contact",
    description: "Used for nominee records and in an emergency",
    icon: Users,
    fields: [
      { key: "father_or_spouse_name", label: "Father’s / spouse’s name", placeholder: "Full name", maxLength: 255 },
      {
        key: "marital_status", label: "Marital status", type: "select",
        options: ["SINGLE", "MARRIED", "DIVORCED", "WIDOWED"].map((m) => ({ value: m, label: humanize(m) })),
        display: humanize,
      },
      {
        key: "blood_group", label: "Blood group", type: "select",
        options: ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"].map((b) => ({ value: b, label: b })),
      },
      { key: "emergency_contact_name", label: "Emergency contact", required: true, placeholder: "Contact person", maxLength: 255 },
      { key: "emergency_contact_relation", label: "Relationship", placeholder: "e.g. Spouse, Father", maxLength: 50 },
      { key: "emergency_contact_phone", label: "Emergency phone", required: true, type: "tel", placeholder: "+91 98765 43210", maxLength: 20 },
    ],
  },
  {
    id: "address",
    title: "Addresses",
    description: "Where you live now and your permanent address",
    icon: MapPin,
    min: 280,
    fields: [
      { key: "current_address", label: "Current address", required: true, type: "textarea", placeholder: "House / flat, street, city, state, PIN", maxLength: 500 },
      { key: "permanent_address", label: "Permanent address", type: "textarea", placeholder: "As on your government ID", maxLength: 500 },
    ],
  },
];

// ─── Document slots ─────────────────────────────────────────────────────────

// "required" mirrors what the backend counts towards completion (kyc/router.py _calc_completion).
interface DocSlot { type: DocumentType; label: string; hint: string; required?: boolean }

const DOC_SLOTS: DocSlot[] = [
  { type: "PAN_CARD", label: "PAN card", hint: "Clear scan or photo of the PAN card", required: true },
  { type: "AADHAAR_FRONT", label: "Aadhaar card", hint: "Front with photo, or the full e-Aadhaar PDF", required: true },
  { type: "BANK_PROOF", label: "Bank proof", hint: "Passbook first page or a cancelled cheque", required: true },
  { type: "PHOTO", label: "Photograph", hint: "Passport-style photo on a plain background" },
  { type: "EDUCATION_CERT", label: "Highest education certificate", hint: "Degree certificate or final marksheet" },
  { type: "EXPERIENCE_LETTER", label: "Relieving / experience letter", hint: "From your previous employer, if any" },
  { type: "ADDRESS_PROOF", label: "Address proof", hint: "Utility bill, rental agreement or passport" },
];

const STATUS_COPY: Record<KycStatus, { title: string; tone: "success" | "info" | "danger" | "brand"; icon: LucideIcon }> = {
  VERIFIED: { title: "KYC verified", tone: "success", icon: ShieldCheck },
  SUBMITTED: { title: "Under HR review", tone: "info", icon: Clock },
  REJECTED: { title: "Changes requested", tone: "danger", icon: AlertTriangle },
  ACTION_REQUIRED: { title: "Changes requested", tone: "danger", icon: AlertTriangle },
  DRAFT: { title: "KYC in progress", tone: "brand", icon: Sparkles },
  NOT_SUBMITTED: { title: "KYC not started", tone: "brand", icon: Sparkles },
};

const TONE_TILE = {
  success: "bg-success/10 text-success",
  info: "bg-info/10 text-info",
  danger: "bg-danger/10 text-danger",
  brand: "bg-brand-500/10 text-accent",
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formFrom(kyc: KycRecord, fields: FieldDef[]) {
  return Object.fromEntries(fields.map((f) => [f.key, kyc[f.key] ?? ""])) as Record<FieldKey, string>;
}

// ─── Main section ───────────────────────────────────────────────────────────

interface KycSectionProps {
  /** If true, this is the employee viewing/editing their own KYC */
  isSelf?: boolean;
  /** If provided, this is HR viewing/managing an employee's KYC */
  employmentId?: string;
  employeeName?: string;
  isHR?: boolean;
}

export function KycSection({ isSelf = false, employmentId, employeeName, isHR = false }: KycSectionProps) {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();

  const queryKey = isSelf ? ["my-kyc"] : ["kyc-employee", employmentId];
  const kycQuery = useQuery({
    queryKey,
    queryFn: () => (isSelf ? kycApi.getMyKyc() : kycApi.getEmployeeKyc(employmentId!)),
    enabled: isSelf || !!employmentId,
  });
  const kyc = kycQuery.data;

  // HR without kyc.write only sees masked numbers and cannot change anything.
  const perms = user?.permissions ?? [];
  const canEdit = isSelf || perms.includes("*") || perms.includes("kyc.write") || perms.includes("people.write");
  const canVerify = isHR && (perms.includes("*") || perms.includes("kyc.verify"));

  const [editing, setEditing] = useState<SectionId | null>(null);
  const [form, setForm] = useState<Record<FieldKey, string>>({} as Record<FieldKey, string>);

  const [previewDoc, setPreviewDoc] = useState<KycDocument | null>(null);
  const [uploadSlot, setUploadSlot] = useState<{ type: DocumentType; label: string } | null>(null);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectDoc, setRejectDoc] = useState<KycDocument | null>(null);
  const [docRejectReason, setDocRejectReason] = useState("");
  const [removeDoc, setRemoveDoc] = useState<KycDocument | null>(null);

  const refreshLists = () => {
    qc.invalidateQueries({ queryKey: ["kyc-employees"] });
    qc.invalidateQueries({ queryKey: ["kyc-summary"] });
  };

  const saveFieldsMutation = useMutation({
    mutationFn: (payload: KycRecordUpdatePayload) =>
      isSelf ? kycApi.updateMyKyc(payload) : kycApi.updateEmployeeKyc(employmentId!, payload),
    onSuccess: (data) => {
      qc.setQueryData(queryKey, data);
      refreshLists();
      setEditing(null);
      toast.success("Details saved");
    },
    onError: (err) => toast.error("Couldn't save details", errorMessage(err)),
  });

  const submitKycMutation = useMutation({
    mutationFn: () => kycApi.submitMyKyc(),
    onSuccess: (data) => {
      qc.setQueryData(queryKey, data);
      refreshLists();
      toast.success("KYC submitted", "HR has been asked to verify your details and documents.");
    },
    onError: (err) => toast.error("Submission failed", errorMessage(err)),
  });

  const verifyOverallMutation = useMutation({
    mutationFn: (body: { status: "VERIFIED" | "REJECTED" | "ACTION_REQUIRED"; rejection_reason?: string }) =>
      kycApi.verifyOverallKyc(employmentId!, body),
    onSuccess: (data) => {
      qc.setQueryData(queryKey, data);
      refreshLists();
      toast.success(data.status === "VERIFIED" ? "KYC verified" : "Changes requested from employee");
      setRejectModalOpen(false);
      setRejectReason("");
    },
    onError: (err) => toast.error("Verification failed", errorMessage(err)),
  });

  const verifyDocMutation = useMutation({
    mutationFn: ({ docId, status, reason }: { docId: string; status: "VERIFIED" | "REJECTED"; reason?: string }) =>
      kycApi.verifyDocument(docId, { status, rejection_reason: reason }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey });
      refreshLists();
      toast.success(vars.status === "VERIFIED" ? "Document approved" : "Document rejected");
      setRejectDoc(null);
      setDocRejectReason("");
      setPreviewDoc(null);
    },
    onError: (err) => toast.error("Couldn't update the document", errorMessage(err)),
  });

  const deleteDocMutation = useMutation({
    mutationFn: (id: string) => kycApi.deleteDocument(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey });
      refreshLists();
      toast.success("Document removed");
      setRemoveDoc(null);
    },
    onError: (err) => toast.error("Couldn't remove the document", errorMessage(err)),
  });

  if (kycQuery.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    );
  }

  if (kycQuery.isError || !kyc) {
    return (
      <div className="card p-6 text-center">
        <AlertTriangle className="mx-auto mb-2 h-7 w-7 text-danger" />
        <p className="text-sm font-semibold text-fg">Unable to load KYC information</p>
        <p className="mt-1 text-xs text-fg-subtle">{errorMessage(kycQuery.error)}</p>
        <button type="button" className="btn-secondary btn-sm mt-4" onClick={() => kycQuery.refetch()}>
          <RefreshCw size={12} /> Try again
        </button>
      </div>
    );
  }

  const status = STATUS_COPY[kyc.status] ?? STATUS_COPY.DRAFT;
  const StatusIcon = status.icon;
  const docsByType = new Map(kyc.documents.map((d) => [d.document_type, d]));
  const extraDocs = kyc.documents.filter((d) => !DOC_SLOTS.some((s) => s.type === d.document_type));
  const requiredSlots = DOC_SLOTS.filter((s) => s.required);
  // The backend accepts either side of the Aadhaar card.
  const hasDoc = (t: DocumentType) => docsByType.has(t) || (t === "AADHAAR_FRONT" && docsByType.has("AADHAAR_BACK"));
  const requiredUploaded = requiredSlots.filter((s) => hasDoc(s.type)).length;
  const verifiedDocs = kyc.documents.filter((d) => d.status === "VERIFIED").length;
  const missingRequiredFields = SECTIONS.flatMap((s) => s.fields).filter((f) => f.required && !kyc[f.key]).length;
  const canSubmit = isSelf && ["NOT_SUBMITTED", "DRAFT", "REJECTED", "ACTION_REQUIRED"].includes(kyc.status);
  const resetsVerification = kyc.status === "VERIFIED" || kyc.status === "SUBMITTED";

  const startEdit = (section: SectionDef) => {
    setForm(formFrom(kyc, section.fields));
    setEditing(section.id);
  };

  const saveSection = (section: SectionDef) => {
    // Only send what changed; blanks clear the field.
    const payload: KycRecordUpdatePayload = {};
    for (const f of section.fields) {
      const next = (form[f.key] ?? "").trim();
      if (next !== (kyc[f.key] ?? "")) payload[f.key] = next || null;
    }
    if (Object.keys(payload).length === 0) {
      setEditing(null);
      return;
    }
    saveFieldsMutation.mutate(payload);
  };

  const description = kyc.status === "VERIFIED"
    ? `All details and documents were approved${kyc.verified_at ? ` on ${format(new Date(kyc.verified_at), "d MMM yyyy")}` : ""}.`
    : kyc.status === "SUBMITTED"
    ? `Submitted${kyc.submitted_at ? ` on ${format(new Date(kyc.submitted_at), "d MMM yyyy")}` : ""}. HR will verify it shortly.`
    : kyc.status === "REJECTED" || kyc.status === "ACTION_REQUIRED"
    ? "HR asked for corrections. Update the items below, then submit again."
    : isSelf
    ? "Fill in the details below and upload the required documents, then submit for verification."
    : "The employee hasn’t submitted their KYC yet.";

  return (
    <div className="space-y-5">
      {/* ── Status overview ─────────────────────────────────────────────── */}
      <section className="card p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3.5">
            <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${TONE_TILE[status.tone]}`}>
              <StatusIcon size={19} />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-[15px] font-semibold text-fg">
                  {employeeName ? `${employeeName} · ` : ""}{status.title}
                </h3>
                <StatusBadge status={kyc.status} />
              </div>
              <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {canSubmit && (
              <button
                type="button"
                onClick={() => submitKycMutation.mutate()}
                disabled={submitKycMutation.isPending || kyc.documents.length === 0 || editing !== null}
                title={editing !== null ? "Save or cancel your edits first" : kyc.documents.length === 0 ? "Upload at least one document first" : undefined}
                className="btn-primary btn-sm"
              >
                {submitKycMutation.isPending ? "Submitting…" : "Submit for verification"}
              </button>
            )}
            {canVerify && kyc.status !== "VERIFIED" && (
              <>
                <button type="button" onClick={() => setRejectModalOpen(true)} className="btn-danger-soft btn-sm">
                  <XCircle size={13} /> Request changes
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
            )}
            {canVerify && kyc.status === "VERIFIED" && (
              <button type="button" onClick={() => setRejectModalOpen(true)} className="btn-secondary btn-sm">
                Revoke verification
              </button>
            )}
          </div>
        </div>

        {(kyc.status === "REJECTED" || kyc.status === "ACTION_REQUIRED") && kyc.rejection_reason && (
          <div className="mt-4 rounded-lg border border-danger/20 bg-danger/[0.05] px-3.5 py-2.5 text-[13px]">
            <span className="font-medium text-danger">HR remarks: </span>
            <span className="text-fg-muted">{kyc.rejection_reason}</span>
          </div>
        )}

        <div className="mt-4 grid gap-x-8 gap-y-3 border-t border-line pt-4 sm:grid-cols-3">
          <div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-fg-subtle">Completion</span>
              <span className="font-semibold tabular-nums text-fg">{kyc.completion_percentage}%</span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-all duration-300 ${kyc.completion_percentage === 100 ? "bg-success" : "bg-brand-500"}`}
                style={{ width: `${kyc.completion_percentage}%` }}
              />
            </div>
          </div>
          <Metric label="Required documents" value={`${requiredUploaded} / ${requiredSlots.length}`} ok={requiredUploaded === requiredSlots.length} />
          <Metric
            label="Required details"
            value={missingRequiredFields === 0 ? "Complete" : `${missingRequiredFields} missing`}
            ok={missingRequiredFields === 0}
            extra={kyc.documents.length > 0 ? `${verifiedDocs} of ${kyc.documents.length} documents verified` : undefined}
          />
        </div>
      </section>

      {/* ── Details (view first, edit on demand) ────────────────────────── */}
      {SECTIONS.map((section) => {
        const isEditing = editing === section.id;
        return (
          <EditableSection
            key={section.id}
            icon={section.icon}
            title={section.title}
            description={section.description}
            editing={isEditing}
            canEdit={canEdit}
            editDisabled={editing !== null && !isEditing}
            onEdit={() => startEdit(section)}
            onCancel={() => setEditing(null)}
            onSubmit={() => saveSection(section)}
            saving={saveFieldsMutation.isPending}
            editNotice={resetsVerification
              ? <span className="text-warning">Saving will send this KYC back for verification.</span>
              : <span>Fields marked <span className="text-danger">*</span> are required for verification.</span>}
          >
            {isEditing ? (
              <FieldGrid min={section.min}>
                {section.fields.map((f) => (
                  <FieldInput
                    key={f.key}
                    field={f}
                    value={form[f.key] ?? ""}
                    onChange={(v) => setForm((prev) => ({ ...prev, [f.key]: v }))}
                    autoFocus={f === section.fields[0]}
                    action={f.key === "permanent_address" ? (
                      <button
                        type="button"
                        disabled={!form.current_address}
                        onClick={() => setForm((prev) => ({ ...prev, permanent_address: prev.current_address }))}
                        className="inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:underline disabled:opacity-50 disabled:no-underline"
                      >
                        <Copy size={11} /> Same as current
                      </button>
                    ) : undefined}
                  />
                ))}
              </FieldGrid>
            ) : (
              <DetailGrid min={section.min}>
                {section.fields.map((f) => (
                  <DetailItem key={f.key} label={f.label} required={f.required}>
                    <FieldValue field={f} value={kyc[f.key]} />
                  </DetailItem>
                ))}
              </DetailGrid>
            )}
          </EditableSection>
        );
      })}

      {/* ── Documents ───────────────────────────────────────────────────── */}
      <section className="card">
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="flex min-w-0 items-start gap-3">
            <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-500/10 text-accent">
              <FolderOpen size={15} />
            </div>
            <div className="min-w-0">
              <h3 className="card-title">Documents</h3>
              <p className="card-desc">PDF, PNG or JPG, up to {MAX_UPLOAD_MB} MB each. Select <span className="font-medium text-fg-muted">View</span> to open a file.</p>
            </div>
          </div>
          <span className="badge badge-neutral shrink-0 tabular-nums">{kyc.documents.length} uploaded</span>
        </div>
        <ul className="divide-y divide-line">
          {DOC_SLOTS.map((slot) => (
            <DocumentRow
              key={slot.type}
              label={slot.label}
              hint={slot.hint}
              required={slot.required}
              document={docsByType.get(slot.type)}
              canManage={canEdit}
              canVerify={canVerify}
              isSelf={isSelf}
              onUpload={() => setUploadSlot({ type: slot.type, label: slot.label })}
              onPreview={setPreviewDoc}
              onApprove={(d) => verifyDocMutation.mutate({ docId: d.id, status: "VERIFIED" })}
              onReject={setRejectDoc}
              onRemove={setRemoveDoc}
            />
          ))}
          {extraDocs.map((d) => (
            <DocumentRow
              key={d.id}
              label={d.document_title || DOCUMENT_TYPE_LABELS[d.document_type]}
              hint=""
              document={d}
              canManage={canEdit}
              canVerify={canVerify}
              isSelf={isSelf}
              onUpload={() => setUploadSlot({ type: d.document_type, label: d.document_title || DOCUMENT_TYPE_LABELS[d.document_type] })}
              onPreview={setPreviewDoc}
              onApprove={(doc) => verifyDocMutation.mutate({ docId: doc.id, status: "VERIFIED" })}
              onReject={setRejectDoc}
              onRemove={setRemoveDoc}
            />
          ))}
        </ul>
      </section>

      {uploadSlot && (
        <UploadDocumentDialog
          employmentId={employmentId}
          type={uploadSlot.type}
          label={uploadSlot.label}
          replacing={docsByType.has(uploadSlot.type)}
          isHR={isHR}
          onClose={() => setUploadSlot(null)}
          onSuccess={() => {
            setUploadSlot(null);
            qc.invalidateQueries({ queryKey });
            refreshLists();
          }}
        />
      )}

      {previewDoc && (
        <DocumentPreviewDialog
          doc={previewDoc}
          onClose={() => setPreviewDoc(null)}
          actions={canVerify ? (
            <>
              {previewDoc.status !== "REJECTED" && (
                <button type="button" className="btn-danger-soft btn-sm" onClick={() => { setRejectDoc(previewDoc); setPreviewDoc(null); }}>
                  <XCircle size={13} /> Reject
                </button>
              )}
              {previewDoc.status !== "VERIFIED" && (
                <button
                  type="button"
                  className="btn-primary btn-sm"
                  disabled={verifyDocMutation.isPending}
                  onClick={() => verifyDocMutation.mutate({ docId: previewDoc.id, status: "VERIFIED" })}
                >
                  <Check size={13} /> Approve
                </button>
              )}
            </>
          ) : undefined}
        />
      )}

      <ConfirmDialog
        open={!!removeDoc}
        onClose={() => setRemoveDoc(null)}
        onConfirm={() => removeDoc && deleteDocMutation.mutate(removeDoc.id)}
        title="Remove this document?"
        description={removeDoc ? `“${removeDoc.file_name}” will be deleted. ${resetsVerification ? "The KYC will need to be verified again." : ""}` : undefined}
        confirmLabel="Remove"
        loading={deleteDocMutation.isPending}
      />

      <Dialog open={rejectModalOpen} onClose={() => setRejectModalOpen(false)}>
        <div className="space-y-4 p-6">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-danger/10 text-danger">
              <AlertTriangle size={18} />
            </div>
            <div>
              <h3 className="text-[15px] font-semibold text-fg">Request KYC corrections</h3>
              <p className="mt-0.5 text-[13px] text-fg-muted">Tell the employee what needs to be corrected.</p>
            </div>
          </div>
          <textarea
            className="input min-h-[96px]"
            placeholder="e.g. Please upload a clearer scan of your Aadhaar card."
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            data-autofocus
          />
        </div>
        <div className="flex justify-end gap-2 border-t border-line bg-panel px-6 py-3.5">
          <button type="button" onClick={() => setRejectModalOpen(false)} className="btn-secondary">Cancel</button>
          <button
            type="button"
            onClick={() => verifyOverallMutation.mutate({
              status: "ACTION_REQUIRED",
              rejection_reason: rejectReason.trim() || "Documents or details require correction",
            })}
            disabled={verifyOverallMutation.isPending}
            className="btn-danger"
          >
            {verifyOverallMutation.isPending ? "Sending…" : "Send to employee"}
          </button>
        </div>
      </Dialog>

      <Dialog open={!!rejectDoc} onClose={() => setRejectDoc(null)}>
        <div className="space-y-4 p-6">
          <div>
            <h3 className="text-[15px] font-semibold text-fg">Reject {rejectDoc?.document_title}</h3>
            <p className="mt-0.5 text-[13px] text-fg-muted">The employee will see this reason next to the document.</p>
          </div>
          <input
            type="text"
            className="input"
            placeholder="e.g. The scan is blurry or cut off"
            value={docRejectReason}
            onChange={(e) => setDocRejectReason(e.target.value)}
            data-autofocus
          />
        </div>
        <div className="flex justify-end gap-2 border-t border-line bg-panel px-6 py-3.5">
          <button type="button" onClick={() => setRejectDoc(null)} className="btn-secondary">Cancel</button>
          <button
            type="button"
            disabled={verifyDocMutation.isPending}
            onClick={() => rejectDoc && verifyDocMutation.mutate({
              docId: rejectDoc.id,
              status: "REJECTED",
              reason: docRejectReason.trim() || "Document does not meet verification requirements",
            })}
            className="btn-danger"
          >
            Reject document
          </button>
        </div>
      </Dialog>
    </div>
  );
}

function Metric({ label, value, ok, extra }: { label: string; value: string; ok: boolean; extra?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-fg-subtle">{label}</p>
      <p className={`mt-0.5 flex items-center gap-1.5 text-[13px] font-semibold ${ok ? "text-success" : "text-fg"}`}>
        {ok && <CheckCircle2 size={13} />}
        {value}
      </p>
      {extra && <p className="truncate text-[11px] text-fg-subtle">{extra}</p>}
    </div>
  );
}

// ─── Field view / input ─────────────────────────────────────────────────────

function FieldValue({ field, value }: { field: FieldDef; value: string | null }) {
  const [revealed, setRevealed] = useState(false);
  if (!value) return <EmptyValue required={field.required} />;

  // Callers without full KYC access already get "••••1234" from the API.
  const serverMasked = value.includes("•");
  const canReveal = field.sensitive && !serverMasked;
  const shown = canReveal && !revealed
    ? `•••• ${value.slice(-4)}`
    : field.display && !serverMasked ? field.display(value) : value;

  return (
    <span className="inline-flex max-w-full items-center gap-1.5">
      <span className={`${field.mono ? "font-mono tracking-wide" : ""} ${field.type === "textarea" ? "whitespace-pre-line font-normal leading-relaxed" : ""}`}>
        {shown}
      </span>
      {canReveal && (
        <button
          type="button"
          onClick={() => setRevealed((r) => !r)}
          className="btn-icon h-6 w-6"
          aria-label={revealed ? `Hide ${field.label}` : `Show ${field.label}`}
          title={revealed ? "Hide" : "Show"}
        >
          {revealed ? <EyeOff size={13} /> : <Eye size={13} />}
        </button>
      )}
    </span>
  );
}

function FieldInput({ field, value, onChange, autoFocus, action }: {
  field: FieldDef;
  value: string;
  onChange: (v: string) => void;
  autoFocus?: boolean;
  action?: ReactNode;
}) {
  const id = `kyc-${field.key}`;
  const common = {
    id,
    value,
    autoFocus,
    maxLength: field.maxLength,
    placeholder: field.placeholder,
    className: `input ${field.mono ? "font-mono tracking-wide" : ""}`,
  };
  const change = (v: string) => onChange(field.normalize ? field.normalize(v) : v);
  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-xs font-medium text-fg-muted">
          {field.label}
          {field.required && <span className="ml-0.5 text-danger">*</span>}
        </label>
        {action}
      </div>
      {field.type === "select" ? (
        <select {...common} onChange={(e) => change(e.target.value)}>
          <option value="">Select…</option>
          {field.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : field.type === "textarea" ? (
        <textarea {...common} rows={3} onChange={(e) => change(e.target.value)} />
      ) : (
        <input {...common} type={field.type === "tel" ? "tel" : "text"} onChange={(e) => change(e.target.value)} />
      )}
      {field.hint && <p className="mt-1 text-[11px] text-fg-subtle">{field.hint}</p>}
    </div>
  );
}

// ─── Document row ───────────────────────────────────────────────────────────

function DocumentRow({
  label, hint, required, document, canManage, canVerify, isSelf,
  onUpload, onPreview, onApprove, onReject, onRemove,
}: {
  label: string;
  hint: string;
  required?: boolean;
  document?: KycDocument;
  canManage: boolean;
  canVerify: boolean;
  isSelf: boolean;
  onUpload: () => void;
  onPreview: (doc: KycDocument) => void;
  onApprove: (doc: KycDocument) => void;
  onReject: (doc: KycDocument) => void;
  onRemove: (doc: KycDocument) => void;
}) {
  const tile = !document
    ? "border border-dashed border-line-strong text-fg-subtle"
    : document.status === "VERIFIED"
    ? "bg-success/10 text-success"
    : document.status === "REJECTED"
    ? "bg-danger/10 text-danger"
    : "bg-brand-500/10 text-accent";
  const Icon = !document ? Upload : document.mime_type.startsWith("image/") ? ImageIcon : FileText;
  // Employees can't change a verified document; HR with write access can.
  const canChange = canManage && !!document && (!isSelf || document.status !== "VERIFIED");

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-3">
      <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${tile}`}>
        <Icon size={16} />
      </div>
      <div className="min-w-0 flex-1 basis-48">
        <p className="flex items-center gap-1.5 text-[13px] font-medium text-fg">
          <span className="truncate">{label}</span>
          {required && <span className="text-danger">*</span>}
        </p>
        {document ? (
          <p className="truncate text-xs text-fg-subtle" title={document.file_name}>
            <span>{document.file_name}</span> · {formatBytes(document.file_size)} · {format(new Date(document.uploaded_at), "d MMM yyyy")}
          </p>
        ) : (
          <p className="truncate text-xs text-fg-subtle">{hint || "Not uploaded"}</p>
        )}
        {document?.status === "REJECTED" && document.rejection_reason && (
          <p className="mt-0.5 text-xs font-medium text-danger">Rejected: {document.rejection_reason}</p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        {document ? <StatusBadge status={document.status} /> : <StatusBadge tone={required ? "warning" : "neutral"} label={required ? "Missing" : "Optional"} />}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {document ? (
          <>
            <button type="button" className="btn-secondary btn-sm" onClick={() => onPreview(document)}>
              <Eye size={13} /> View
            </button>
            <DocumentDownload document={document} className="btn-icon" title="Download">
              <Download size={14} />
            </DocumentDownload>
            {canVerify && document.status !== "VERIFIED" && (
              <button type="button" className="btn-icon text-success hover:bg-success/10 hover:text-success" title="Approve" aria-label={`Approve ${label}`} onClick={() => onApprove(document)}>
                <Check size={15} />
              </button>
            )}
            {canVerify && document.status !== "REJECTED" && (
              <button type="button" className="btn-icon text-danger hover:bg-danger/10 hover:text-danger" title="Reject" aria-label={`Reject ${label}`} onClick={() => onReject(document)}>
                <XCircle size={15} />
              </button>
            )}
            {canChange && (
              <>
                <button type="button" className="btn-icon" title="Replace file" aria-label={`Replace ${label}`} onClick={onUpload}>
                  <RefreshCw size={14} />
                </button>
                <button type="button" className="btn-icon hover:text-danger" title="Remove" aria-label={`Remove ${label}`} onClick={() => onRemove(document)}>
                  <Trash2 size={14} />
                </button>
              </>
            )}
          </>
        ) : canManage ? (
          <button type="button" className="btn-secondary btn-sm" onClick={onUpload}>
            <Upload size={13} /> Upload
          </button>
        ) : null}
      </div>
    </li>
  );
}

// ─── Dialogs ────────────────────────────────────────────────────────────────

function UploadDocumentDialog({ employmentId, type, label, replacing, isHR, onClose, onSuccess }: {
  employmentId?: string;
  type: DocumentType;
  label: string;
  replacing: boolean;
  isHR: boolean;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docNumber, setDocNumber] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = (f: File | undefined) => {
    if (!f) return;
    if (!/\.(pdf|png|jpe?g)$/i.test(f.name)) {
      setError("Only PDF, PNG or JPG files are accepted.");
      return;
    }
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`This file is ${formatBytes(f.size)}. The limit is ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    setError(null);
    setFile(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    try {
      const title = DOCUMENT_TYPE_LABELS[type];
      if (isHR && employmentId) {
        await kycApi.uploadEmployeeDocument(employmentId, file, type, title, docNumber.trim() || undefined);
      } else {
        await kycApi.uploadMyDocument(file, type, title, docNumber.trim() || undefined);
      }
      toast.success(replacing ? "Document replaced" : "Document uploaded");
      onSuccess();
    } catch (err) {
      toast.error("Upload failed", errorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Dialog open={true} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <div className="space-y-4 p-6">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-500/10 text-accent">
              <Upload size={18} />
            </div>
            <div>
              <h3 className="text-[15px] font-semibold text-fg">{replacing ? "Replace" : "Upload"} {label.toLowerCase()}</h3>
              <p className="mt-0.5 text-[13px] text-fg-muted">PDF, PNG or JPG, up to {MAX_UPLOAD_MB} MB</p>
            </div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg"
            onChange={(e) => pick(e.target.files?.[0])}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`block w-full rounded-xl border-2 border-dashed p-6 text-center transition-colors ${
              dragging || file ? "border-brand-500 bg-brand-500/[0.04]" : "border-line hover:border-brand-500/50 bg-canvas"
            }`}
          >
            <FileUp className="mx-auto mb-2 h-7 w-7 text-accent" />
            {file ? (
              <span className="block text-[13px]">
                <span className="block truncate font-medium text-fg">{file.name}</span>
                <span className="mt-0.5 block text-xs text-fg-subtle">{formatBytes(file.size)} · Click to choose another file</span>
              </span>
            ) : (
              <span className="block text-[13px] text-fg-subtle">
                <span className="font-medium text-accent">Choose a file</span> or drag it here
              </span>
            )}
          </button>
          {error && <p className="text-xs font-medium text-danger" role="alert">{error}</p>}

          <div>
            <label className="label" htmlFor="kyc-doc-number">
              Document number <span className="font-normal text-fg-subtle">(optional)</span>
            </label>
            <input
              id="kyc-doc-number"
              type="text"
              maxLength={100}
              placeholder="Number printed on the card or certificate"
              value={docNumber}
              onChange={(e) => setDocNumber(e.target.value)}
              className="input font-mono"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-line bg-panel px-6 py-3.5">
          <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={!file || uploading} className="btn-primary">
            {uploading ? "Uploading…" : replacing ? "Replace document" : "Upload document"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function DocumentPreviewDialog({ doc, onClose, actions }: {
  doc: KycDocument;
  onClose: () => void;
  actions?: ReactNode;
}) {
  const [preview, setPreview] = useState<{ url?: string; type?: string; error?: string }>({});
  useEffect(() => {
    let active = true;
    let objectUrl: string | undefined;
    kycApi.fetchDocumentBlob(doc.preview_url).then(({ blob, url }) => {
      URL.revokeObjectURL(url);
      // Only the types the server accepts on upload are rendered inline. A sandboxed
      // iframe can't host the browser's PDF viewer, so PDFs go in an <object> instead.
      if (!PREVIEWABLE.has(blob.type)) {
        if (active) setPreview({ error: "This file type can't be previewed. Download it instead." });
        return;
      }
      objectUrl = URL.createObjectURL(new Blob([blob], { type: blob.type }));
      if (active) setPreview({ url: objectUrl, type: blob.type });
      else URL.revokeObjectURL(objectUrl);
    }).catch(() => { if (active) setPreview({ error: "Couldn't load this document." }); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [doc.preview_url]);

  return (
    <Dialog open={true} onClose={onClose} className="max-w-3xl">
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-[15px] font-semibold text-fg">{doc.document_title}</h3>
            <StatusBadge status={doc.status} />
          </div>
          <p className="mt-0.5 truncate text-xs text-fg-subtle">
            {doc.file_name} · {formatBytes(doc.file_size)} · Uploaded {format(new Date(doc.uploaded_at), "d MMM yyyy, h:mm a")}
            {doc.document_number ? ` · No. ${doc.document_number}` : ""}
          </p>
          {doc.status === "REJECTED" && doc.rejection_reason && (
            <p className="mt-1 text-xs font-medium text-danger">Rejected: {doc.rejection_reason}</p>
          )}
        </div>
        <button type="button" onClick={onClose} className="btn-icon shrink-0" aria-label="Close">
          <X size={16} />
        </button>
      </div>

      <div className="grid h-[60vh] place-items-center overflow-auto bg-canvas p-3">
        {preview.error ? (
          <p className="text-[13px] text-danger" role="alert">{preview.error}</p>
        ) : !preview.url ? (
          <Skeleton className="h-full w-full rounded-lg" />
        ) : preview.type?.startsWith("image/") ? (
          <img src={preview.url} alt={doc.document_title} className="max-h-full max-w-full rounded-lg object-contain shadow-card" />
        ) : (
          <object data={preview.url} type="application/pdf" aria-label={doc.document_title} className="h-full w-full rounded-lg bg-surface">
            <div className="grid h-full place-items-center p-6 text-center text-[13px] text-fg-muted">
              This browser can’t show PDFs inline. Use Download to open it.
            </div>
          </object>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-panel px-5 py-3">
        <DocumentDownload document={doc} className="btn-secondary btn-sm">
          <Download size={13} /> Download
        </DocumentDownload>
        <div className="flex items-center gap-2">
          {actions}
          <button type="button" onClick={onClose} className="btn-ghost btn-sm">Close</button>
        </div>
      </div>
    </Dialog>
  );
}

function DocumentDownload({ document, children, ...props }: {
  document: KycDocument; children: ReactNode; className?: string; title?: string;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      const { url } = await kycApi.fetchDocumentBlob(document.download_url);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = document.file_name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      toast.error("Download failed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" {...props} aria-label={props.title} onClick={download} disabled={busy}>
      {children}
    </button>
  );
}

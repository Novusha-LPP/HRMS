import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addDays, format, parseISO } from "date-fns";
import { orgApi } from "../../api/org";
import { peopleApi, personnelActionsApi, rejoinApi, separationApi } from "../../api/people";
import type { PersonnelActionChanges, RejoinMode } from "../../api/people";
import { MODE_HELP, MODE_LABEL, buildRejoinChoice, days, describeGap, describeSettlement, ACTION_LABEL } from "../../lib/rejoin";
import { formatDateOnly } from "../../lib/dates";
import { Sheet } from "../ui/Overlay";
import { Notice } from "../ui/Feedback";
import { UsageHelpButton } from "../ui/UsageHelpButton";
import { useToast, errorMessage } from "../ui/Toast";
import { PlacementFields } from "./PlacementFields";
import { ACTION_META } from "../../lib/personnelActions";
import type { ActionKind } from "../../lib/personnelActions";
import type { PlacementValues } from "./PlacementFields";

export interface ActionSubject {
  id: string;
  name: string;
  state: string;
  hireDate: string;
  legalEntityId?: string;
  jobId?: string;
  designation?: string;
  gradeId?: string;
  grade?: string;
  positionId?: string;
  positionTitle?: string;
  managerEmploymentId?: string;
  manager?: string;
}

const today = () => format(new Date(), "yyyy-MM-dd");
const OTHER = "__other__";

export function PersonnelActionSheet({ subject, kind, onClose }: {
  subject: ActionSubject | null;
  kind: ActionKind | null;
  onClose: () => void;
}) {
  const open = !!subject && !!kind;
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={subject && kind ? `${ACTION_META[kind].title} — ${subject.name}` : "Personnel action"}
      description={kind ? ACTION_META[kind].description : undefined}
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        {kind && <button className="btn-primary" type="submit" form="personnel-action">{ACTION_META[kind].submit}</button>}
      </>}
    >
      {subject && kind && <ActionForm key={`${subject.id}-${kind}`} subject={subject} kind={kind} onDone={onClose} />}
    </Sheet>
  );
}

function ActionForm({ subject, kind, onDone }: { subject: ActionSubject; kind: ActionKind; onDone: () => void }) {
  const meta = ACTION_META[kind];
  const qc = useQueryClient();
  const toast = useToast();
  const [date, setDate] = useState(today());
  const [reason, setReason] = useState("");
  const [otherReason, setOtherReason] = useState("");
  const [jobId, setJobId] = useState(subject.jobId ?? "");
  const [gradeId, setGradeId] = useState(subject.gradeId ?? "");
  const [positionId, setPositionId] = useState(subject.positionId ?? "");
  const [managerId, setManagerId] = useState(subject.managerEmploymentId ?? "");
  const [until, setUntil] = useState("");
  const [placement, setPlacement] = useState<PlacementValues>({ orgUnitId: "", jobId: "", locationId: "", managerEmploymentId: "" });
  // Rejoin only: "" means "use the company's default".
  const [rejoinMode, setRejoinMode] = useState<RejoinMode | "">("");
  const [condoned, setCondoned] = useState(false);
  const [rejoinReason, setRejoinReason] = useState("");
  const [gratuityPaid, setGratuityPaid] = useState(false);
  const [settledReason, setSettledReason] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setSettledReason(rejoinReason.trim()), 350);
    return () => clearTimeout(t);
  }, [rejoinReason]);

  const needsJobs = kind === "PROMOTION" || kind === "CHANGE_JOB";
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => orgApi.listJobs(), enabled: needsJobs });
  const grades = useQuery({ queryKey: ["grades"], queryFn: () => orgApi.listGrades(), enabled: kind === "PROMOTION" });
  const positions = useQuery({ queryKey: ["positions"], queryFn: () => orgApi.listPositions(), enabled: kind === "PROMOTION" });
  const employees = useQuery({ queryKey: ["employees"], queryFn: () => peopleApi.listAllEmployees(), enabled: kind === "CHANGE_MANAGER" });

  const reasonCode = reason === OTHER ? otherReason.trim() : reason;
  const isSeparation = kind === "SEPARATION";
  // A separation takes effect the day after the last working day: attendance and headcount
  // still count the employee on the last day itself.
  const effectiveDate = isSeparation && date ? format(addDays(parseISO(date), 1), "yyyy-MM-dd") : date;
  const scheduled = effectiveDate > today();

  const rejoinPreview = useQuery({
    queryKey: ["rejoin-preview", subject.id, effectiveDate, rejoinMode, condoned, settledReason, gratuityPaid],
    queryFn: () => rejoinApi.preview(subject.id, {
      effective_date: effectiveDate, mode: rejoinMode || undefined, break_condoned: condoned,
      reason: settledReason || undefined, gratuity_paid_at_exit: gratuityPaid || undefined,
    }),
    enabled: kind === "REHIRE" && !!effectiveDate,
    retry: false,
  });
  const leavePreview = useQuery({
    queryKey: ["separation-preview", subject.id, effectiveDate],
    queryFn: () => separationApi.preview(subject.id, effectiveDate),
    enabled: isSeparation && !!date,
    retry: false,
  });

  const changes = (): PersonnelActionChanges | undefined => {
    switch (kind) {
      case "PROMOTION": {
        const c: PersonnelActionChanges = {};
        if (jobId && jobId !== subject.jobId) c.job_id = jobId;
        if (gradeId && gradeId !== subject.gradeId) c.grade_id = gradeId;
        if (positionId && positionId !== subject.positionId) c.position_id = positionId;
        return c;
      }
      case "CHANGE_JOB": return { job_id: jobId };
      case "CHANGE_MANAGER": return { manager_employment_id: managerId };
      case "EXTEND_PROBATION": return { probation_extended_until: until };
      case "PLACE_ON_NOTICE": return until ? { expected_last_working_day: until } : undefined;
      case "SEPARATION": return { last_working_day: date };
      case "REHIRE": return {
        org_unit_id: placement.orgUnitId, job_id: placement.jobId, location_id: placement.locationId,
        manager_employment_id: placement.managerEmploymentId || undefined,
      };
      default: return undefined;
    }
  };

  const problems: string[] = [];
  if (!date) problems.push("Choose a date.");
  if (date && date < subject.hireDate && kind !== "REHIRE") problems.push(`The date can't be before they joined (${formatDateOnly(subject.hireDate)}).`);
  if (meta.reasonRequired && !reasonCode) problems.push("Choose a reason.");
  if (reason === OTHER && !otherReason.trim()) problems.push("Describe the reason.");
  if (kind === "PROMOTION" && !Object.keys(changes() ?? {}).length) problems.push("Change the designation, grade or position.");
  if (kind === "CHANGE_JOB" && (!jobId || jobId === subject.jobId)) problems.push("Choose a different designation.");
  if (kind === "CHANGE_MANAGER" && (!managerId || managerId === subject.managerEmploymentId)) problems.push("Choose a different manager.");
  if (kind === "EXTEND_PROBATION" && (!until || until <= date)) problems.push("Choose when the extended probation ends.");
  if (kind === "PLACE_ON_NOTICE" && until && until < date) problems.push("The expected last day can't be before notice starts.");
  if (kind === "REHIRE" && (!placement.orgUnitId || !placement.jobId || !placement.locationId)) problems.push("Choose a department, designation and location.");

  // A rejoin the company's rules rule out is explained in the panel itself. Only trust the
  // preview once it reflects what is typed; until then the server decides when saving.
  const previewIsCurrent = !rejoinPreview.isFetching && settledReason === rejoinReason.trim();
  if (kind === "REHIRE" && previewIsCurrent && rejoinPreview.data && !rejoinPreview.data.can_proceed) {
    problems.push("Resolve what is shown under Service and leave.");
  }

  const save = useMutation({
    mutationFn: () => personnelActionsApi.create({
      employment_id: subject.id, type: kind, effective_date: effectiveDate,
      reason_code: reasonCode || undefined, changes: changes(),
      rejoin: kind === "REHIRE"
        ? buildRejoinChoice({ mode: rejoinMode, condoned, reason: rejoinReason, gratuityPaid })
        : undefined,
    }),
    onSuccess: (pa) => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      qc.invalidateQueries({ queryKey: ["personnel-actions", subject.id] });
      qc.invalidateQueries({ queryKey: ["positions"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(
        pa.status === "SCHEDULED" ? `${meta.title} scheduled` : meta.success,
        pa.status === "SCHEDULED" ? `${subject.name} · applies on ${formatDateOnly(pa.effective_date)}` : subject.name,
      );
      onDone();
    },
    onError: (e) => toast.error(`Couldn’t record the ${meta.title.toLowerCase()}`, errorMessage(e)),
  });

  const [tried, setTried] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!problems.length && !save.isPending) save.mutate();
  };

  const entityPositions = (positions.data ?? []).filter((p) => p.status === "ACTIVE" && (!subject.legalEntityId || p.legal_entity_id === subject.legalEntityId));
  const managers = (employees.data ?? []).filter((e) => e.legal_entity_id === subject.legalEntityId && e.id !== subject.id && e.employment_state !== "SEPARATED");
  const sortedJobs = [...(jobs.data ?? [])].sort((a, b) => a.title.localeCompare(b.title));

  return (
    <form id="personnel-action" onSubmit={submit} className="space-y-4">
      {(kind === "PROMOTION" || kind === "CHANGE_JOB" || kind === "CHANGE_MANAGER") && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-xl border border-line bg-muted/40 px-4 py-3 text-[13px]">
          {kind !== "CHANGE_MANAGER" && <><dt className="text-fg-subtle">Designation now</dt><dd className="font-medium text-fg">{subject.designation ?? "—"}</dd></>}
          {kind === "PROMOTION" && <><dt className="text-fg-subtle">Grade now</dt><dd className="font-medium text-fg">{subject.grade ?? "—"}</dd></>}
          {kind === "PROMOTION" && subject.positionTitle && <><dt className="text-fg-subtle">Position now</dt><dd className="font-medium text-fg">{subject.positionTitle}</dd></>}
          {kind === "CHANGE_MANAGER" && <><dt className="text-fg-subtle">Reports to now</dt><dd className="font-medium text-fg">{subject.manager ?? "No manager"}</dd></>}
        </dl>
      )}

      {needsJobs && (
        <div>
          <label className="label" htmlFor="pa-job">New designation{kind === "PROMOTION" && <span className="font-normal text-fg-subtle"> (optional)</span>}</label>
          <select id="pa-job" className="input" value={jobId} onChange={(e) => setJobId(e.target.value)}>
            <option value="">Choose…</option>
            {sortedJobs.filter((j) => j.status === "ACTIVE" || j.id === jobId).map((j) => <option key={j.id} value={j.id}>{j.title}{j.id === subject.jobId ? " (current)" : ""}</option>)}
          </select>
        </div>
      )}

      {kind === "PROMOTION" && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="pa-grade">New grade <span className="font-normal text-fg-subtle">(optional)</span></label>
            <select id="pa-grade" className="input" value={gradeId} onChange={(e) => setGradeId(e.target.value)}>
              <option value="">{grades.data?.length ? "Choose…" : "No grades set up"}</option>
              {(grades.data ?? []).filter((g) => g.status === "ACTIVE" || g.id === gradeId).map((g) => <option key={g.id} value={g.id}>{g.code} · {g.name}{g.id === subject.gradeId ? " (current)" : ""}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="pa-pos">New position <span className="font-normal text-fg-subtle">(optional)</span></label>
            <select id="pa-pos" className="input" value={positionId} onChange={(e) => setPositionId(e.target.value)}>
              <option value="">{entityPositions.length ? "Choose…" : "No positions set up"}</option>
              {entityPositions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title} · {p.org_unit_name}{p.vacancies != null ? ` · ${p.vacancies} open` : ""}{p.id === subject.positionId ? " (current)" : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {kind === "CHANGE_MANAGER" && (
        <div>
          <label className="label" htmlFor="pa-mgr">New manager</label>
          <select id="pa-mgr" className="input" value={managerId} onChange={(e) => setManagerId(e.target.value)}>
            <option value="">Choose…</option>
            {managers.map((m) => <option key={m.id} value={m.id}>{m.full_name ?? m.employee_number} · {m.employee_number}{m.designation ? ` · ${m.designation}` : ""}</option>)}
          </select>
        </div>
      )}

      {kind === "REHIRE" && (
        <PlacementFields
          legalEntityId={subject.legalEntityId ?? ""}
          values={placement}
          onChange={(v) => setPlacement((p) => ({ ...p, ...v }))}
          excludeEmploymentId={subject.id}
        />
      )}

      {kind === "REHIRE" && (
        <RejoinPanel
          preview={rejoinPreview.data}
          loading={rejoinPreview.isFetching}
          mode={rejoinMode} onMode={setRejoinMode}
          condoned={condoned} onCondoned={setCondoned}
          reason={rejoinReason} onReason={setRejoinReason}
          gratuityPaid={gratuityPaid} onGratuityPaid={setGratuityPaid}
        />
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="pa-date">{meta.dateLabel}</label>
          <input id="pa-date" type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        {kind === "EXTEND_PROBATION" && (
          <div>
            <label className="label" htmlFor="pa-until">Probation now ends on</label>
            <input id="pa-until" type="date" className="input" min={date} value={until} onChange={(e) => setUntil(e.target.value)} />
          </div>
        )}
        {kind === "PLACE_ON_NOTICE" && (
          <div>
            <label className="label" htmlFor="pa-until">Expected last day <span className="font-normal text-fg-subtle">(optional)</span></label>
            <input id="pa-until" type="date" className="input" min={date} value={until} onChange={(e) => setUntil(e.target.value)} />
          </div>
        )}
      </div>

      <div>
        <label className="label" htmlFor="pa-reason">Reason{!meta.reasonRequired && <span className="font-normal text-fg-subtle"> (optional)</span>}</label>
        <select id="pa-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="">{meta.reasonRequired ? "Choose…" : "—"}</option>
          {meta.reasons.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          <option value={OTHER}>Other…</option>
        </select>
        {reason === OTHER && (
          <input className="input mt-2" maxLength={100} placeholder="Describe the reason" value={otherReason} onChange={(e) => setOtherReason(e.target.value)} />
        )}
      </div>

      {isSeparation && date && (
        <Notice title={`Employed up to and including ${formatDateOnly(date)}`} tone="warning">
          From {formatDateOnly(effectiveDate)} {subject.name} is shown as separated, and stops counting in attendance and headcount.
        </Notice>
      )}
      {isSeparation && (leavePreview.data?.items.length ?? 0) > 0 && (
        <div className="rounded-xl border border-line bg-surface-raised p-4 text-[13px]" data-testid="separation-leave">
          <p className="font-medium text-fg">Unused leave when they leave</p>
          <ul className="mt-2 space-y-1 text-fg-muted">
            {leavePreview.data!.items.map((i) => (
              <li key={i.leave_type_id}>
                <span className="font-medium text-fg">{i.leave_type_name}</span>: {days(i.unused_days)} unused · {ACTION_LABEL[i.action]} — {describeSettlement(i)}
                {i.note && <span className="block text-xs text-fg-subtle">{i.note}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-fg-subtle">This follows your company's leave rules for leavers and is recorded in each person's leave history.</p>
        </div>
      )}
      {scheduled && !isSeparation && (
        <p className="text-xs text-fg-subtle">This date is in the future: the change is scheduled and applies automatically on {formatDateOnly(effectiveDate)}. You can cancel it until then.</p>
      )}
      {scheduled && isSeparation && (
        <p className="text-xs text-fg-subtle">The separation is scheduled and applies automatically. You can cancel it until then.</p>
      )}

      {tried && problems.length > 0 && (
        <ul className="space-y-1 text-xs text-danger">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
      {save.isPending && <p className="text-xs text-fg-subtle">Saving…</p>}
    </form>
  );
}


function RejoinPanel({ preview, loading, mode, onMode, condoned, onCondoned, reason, onReason, gratuityPaid, onGratuityPaid }: {
  preview: import("../../api/people").RejoinPreview | undefined;
  loading: boolean;
  mode: RejoinMode | "";
  onMode: (m: RejoinMode | "") => void;
  condoned: boolean;
  onCondoned: (v: boolean) => void;
  reason: string;
  onReason: (v: string) => void;
  gratuityPaid: boolean;
  onGratuityPaid: (v: boolean) => void;
}) {
  const effective = preview?.mode ?? (mode || "CONTINUE");
  const overLimit = !!preview && preview.force_fresh_after_days !== null && (preview.gap_days ?? 0) > preview.force_fresh_after_days;
  const needsReason = effective === "FRESH" || (effective === "CONTINUE" && condoned);
  return (
    <fieldset className="space-y-3 rounded-xl border border-line p-4" data-testid="rejoin-panel">
      <legend className="px-1 text-sm font-semibold text-fg">Service and leave <UsageHelpButton topic="rejoin" iconOnly /></legend>
      {preview && (
        <p className="text-[13px] text-fg-muted">
          Left on {preview.left_on ?? "—"} · break of <span className="font-medium text-fg">{describeGap(preview.gap_days)}</span>
          {preview.force_fresh_after_days !== null && <> · company limit for continuing: {preview.force_fresh_after_days} days</>}
        </p>
      )}
      <div className="space-y-2" role="radiogroup" aria-label="What happens to earlier service and leave">
        <label className="flex items-start gap-2 text-[13px]">
          <input type="radio" name="rejoin-mode" checked={mode === ""} onChange={() => onMode("")} />
          <span><span className="font-medium text-fg">Follow the company default</span>{preview && <span className="text-fg-muted"> ({MODE_LABEL[preview.default_mode]})</span>}</span>
        </label>
        {(["CONTINUE", "FRESH"] as RejoinMode[]).map((m) => (
          <label key={m} className="flex items-start gap-2 text-[13px]">
            <input type="radio" name="rejoin-mode" checked={mode === m} onChange={() => onMode(m)} />
            <span><span className="font-medium text-fg">{MODE_LABEL[m]}</span><span className="block text-xs text-fg-muted">{MODE_HELP[m]}</span></span>
          </label>
        ))}
      </div>
      <label className="flex items-start gap-2 text-[13px]">
        <input type="checkbox" checked={gratuityPaid} onChange={(e) => onGratuityPaid(e.target.checked)} />
        <span>Gratuity was paid when they left <span className="block text-xs text-fg-muted">Service then restarts, so they can only start fresh.</span></span>
      </label>
      {overLimit && effective === "CONTINUE" && !gratuityPaid && (
        <label className="flex items-start gap-2 text-[13px]">
          <input type="checkbox" checked={condoned} onChange={(e) => onCondoned(e.target.checked)} />
          <span>I accept this break as not interrupting service <span className="block text-xs text-fg-muted">Needed to continue after a break longer than your company allows. Give a reason below.</span></span>
        </label>
      )}
      {(needsReason || mode === "FRESH") && (
        <div>
          <label className="label" htmlFor="pa-rejoin-reason">Reason for this choice</label>
          <input id="pa-rejoin-reason" className="input" maxLength={300} value={reason} onChange={(e) => onReason(e.target.value)} placeholder="For example: new contract, or approved by the director" />
        </div>
      )}
      {preview && preview.leave.length > 0 && (
        <table className="w-full text-[13px]">
          <thead><tr className="text-left text-xs text-fg-subtle"><th className="py-1 font-medium">Leave</th><th className="py-1 font-medium">Unused</th><th className="py-1 font-medium">After rejoining</th></tr></thead>
          <tbody>
            {preview.leave.map((l) => (
              <tr key={l.leave_type_id} className="border-t border-line">
                <td className="py-1">{l.leave_type_name}</td>
                <td className="py-1">{days(l.days)}</td>
                <td className="py-1">{l.outcome === "KEPT" ? "Kept" : "Lapses"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {preview && preview.blocked.length > 0 && (
        <ul className="space-y-1 text-xs text-danger" role="alert">{preview.blocked.map((b) => <li key={b}>{b}</li>)}</ul>
      )}
      {preview && preview.notes.map((n) => <p key={n} className="text-xs text-fg-subtle">{n}</p>)}
      {preview?.automatic && mode === "" && preview.mode !== preview.default_mode && (
        <Notice tone="warning" title={`This will start fresh`}>{preview.reason}</Notice>
      )}
      {loading && !preview && <p className="text-xs text-fg-subtle">Checking…</p>}
    </fieldset>
  );
}

import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addDays, format, parseISO } from "date-fns";
import { orgApi } from "../../api/org";
import { peopleApi, personnelActionsApi } from "../../api/people";
import type { PersonnelActionChanges } from "../../api/people";
import { formatDateOnly } from "../../lib/dates";
import { Sheet } from "../ui/Overlay";
import { Notice } from "../ui/Feedback";
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

  const save = useMutation({
    mutationFn: () => personnelActionsApi.create({
      employment_id: subject.id, type: kind, effective_date: effectiveDate,
      reason_code: reasonCode || undefined, changes: changes(),
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

import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Sheet } from "../ui/Overlay";
import { Notice } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { recruitmentApi } from "../../api/recruitment";
import type { EmploymentType, OpeningDetail, OpeningInput, OpeningReason, Priority, WorkMode } from "../../api/recruitment";
import { EMPLOYMENT_TYPES, PRIORITY, REASONS, WORK_MODES } from "./meta";
import { TagInput } from "./TagInput";

type Form = {
  title: string;
  orgUnitId: string;
  jobId: string;
  locationId: string;
  managerId: string;
  employmentType: EmploymentType;
  workMode: WorkMode;
  positions: string;
  priority: Priority;
  reason: OpeningReason;
  replacementFor: string;
  minExp: string;
  maxExp: string;
  salaryMin: string;
  salaryMax: string;
  currency: string;
  targetDate: string;
  description: string;
  responsibilities: string;
  requirements: string;
  skills: string[];
};

function fromOpening(o: OpeningDetail | null): Form {
  return {
    title: o?.title ?? "",
    orgUnitId: o?.org_unit_id ?? "",
    jobId: o?.job_id ?? "",
    locationId: o?.location_id ?? "",
    managerId: o?.hiring_manager_employment_id ?? "",
    employmentType: o?.employment_type ?? "FULL_TIME",
    workMode: o?.work_mode ?? "ONSITE",
    positions: String(o?.positions ?? 1),
    priority: o?.priority ?? "MEDIUM",
    reason: o?.reason ?? "NEW_ROLE",
    replacementFor: o?.replacement_for ?? "",
    minExp: o?.min_experience_years ? String(Number(o.min_experience_years)) : "",
    maxExp: o?.max_experience_years ? String(Number(o.max_experience_years)) : "",
    salaryMin: o?.salary_min ? String(Number(o.salary_min)) : "",
    salaryMax: o?.salary_max ? String(Number(o.salary_max)) : "",
    currency: o?.currency ?? "INR",
    targetDate: o?.target_start_date ?? "",
    description: o?.description ?? "",
    responsibilities: o?.responsibilities ?? "",
    requirements: o?.requirements ?? "",
    skills: o?.skills ?? [],
  };
}

const num = (v: string) => (v.trim() === "" ? null : Number(v));

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-[13px] font-semibold text-fg">{title}</h3>
        {description && <p className="text-xs text-fg-subtle">{description}</p>}
      </div>
      {children}
    </section>
  );
}

/** Raise a new opening, or edit one (drafts / rejected by the requester; live ones by HR). */
export function OpeningFormSheet({ open, onClose, opening }: {
  open: boolean;
  onClose: () => void;
  opening?: OpeningDetail | null;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const editing = !!opening;
  const access = useQuery({ queryKey: ["recruitment-access"], queryFn: recruitmentApi.access, enabled: open });

  const [form, setForm] = useState<Form>(() => fromOpening(opening ?? null));
  const [lastKey, setLastKey] = useState(`${open}-${opening?.id ?? "new"}-${opening?.version ?? 0}`);
  const key = `${open}-${opening?.id ?? "new"}-${opening?.version ?? 0}`;
  if (key !== lastKey) {
    setLastKey(key);
    setForm(fromOpening(opening ?? null));
  }

  const set = <K extends keyof Form>(k: K) => (v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const departments = access.data?.departments ?? [];
  const unit = departments.find((d) => d.id === form.orgUnitId);
  const locations = (access.data?.locations ?? []).filter((l) => !l.legal_entity_id || !unit || l.legal_entity_id === unit.legal_entity_id);

  // Default the department when the caller can only raise for one.
  if (!editing && !form.orgUnitId && departments.length === 1) {
    setForm((f) => ({ ...f, orgUnitId: departments[0].id }));
  }

  const body = (): OpeningInput => ({
    title: form.title.trim(),
    org_unit_id: form.orgUnitId,
    job_id: form.jobId || null,
    location_id: form.locationId || null,
    hiring_manager_employment_id: form.managerId || null,
    employment_type: form.employmentType,
    work_mode: form.workMode,
    positions: Number(form.positions) || 1,
    priority: form.priority,
    reason: form.reason,
    replacement_for: form.reason === "REPLACEMENT" ? form.replacementFor.trim() || null : null,
    min_experience_years: num(form.minExp),
    max_experience_years: num(form.maxExp),
    salary_min: num(form.salaryMin),
    salary_max: num(form.salaryMax),
    currency: form.currency.trim().toUpperCase() || "INR",
    target_start_date: form.targetDate || null,
    description: form.description.trim(),
    responsibilities: form.responsibilities.trim() || null,
    requirements: form.requirements.trim() || null,
    skills: form.skills,
  });

  const save = useMutation({
    mutationFn: (submit: boolean) =>
      editing
        ? recruitmentApi.updateOpening(opening!.id, { ...body(), version: opening!.version })
        : recruitmentApi.createOpening(body(), submit),
    onSuccess: (saved, submit) => {
      qc.invalidateQueries({ queryKey: ["recruitment-openings"] });
      qc.setQueryData(["recruitment-opening", saved.id], saved);
      qc.invalidateQueries({ queryKey: ["recruitment-events", saved.id] });
      if (editing) toast.success("Opening updated");
      else if (!submit) toast.success("Draft saved", `${saved.code} · submit it for approval when ready`);
      else if (saved.status === "OPEN") toast.success("Opening is live", `${saved.code} · start adding candidates`);
      else toast.success("Sent for approval", `${saved.code} · you’ll see the decision here`);
      onClose();
      if (!editing) navigate(`/recruitment/openings/${saved.id}`);
    },
    onError: (e) => toast.error(editing ? "Couldn’t update the opening" : "Couldn’t save the opening", errorMessage(e)),
  });

  const minExp = num(form.minExp);
  const maxExp = num(form.maxExp);
  const salMin = num(form.salaryMin);
  const salMax = num(form.salaryMax);
  const problems = [
    minExp !== null && maxExp !== null && maxExp < minExp && "Maximum experience is below the minimum.",
    salMin !== null && salMax !== null && salMax < salMin && "Maximum salary is below the minimum.",
    form.reason === "REPLACEMENT" && !form.replacementFor.trim() && "Say who this opening replaces.",
  ].filter(Boolean) as string[];
  const valid = form.title.trim().length >= 2 && form.orgUnitId && form.description.trim().length >= 10
    && Number(form.positions) >= 1 && problems.length === 0;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) save.mutate(!editing);
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      className="max-w-2xl"
      title={editing ? `Edit ${opening!.code}` : "Raise a job opening"}
      description={editing ? opening!.title : "Describe the role. It goes to approval before HR starts hiring."}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          {!editing && (
            <button type="button" className="btn-secondary" disabled={!valid || save.isPending} onClick={() => save.mutate(false)}>
              Save as draft
            </button>
          )}
          <button type="submit" form="opening-form" className="btn-primary" disabled={!valid || save.isPending}>
            {save.isPending ? "Saving…" : editing ? "Save changes" : access.data?.can_approve ? "Publish opening" : "Submit for approval"}
          </button>
        </>
      }
    >
      <form id="opening-form" onSubmit={submit} className="space-y-7">
        {access.isError && <Notice title="Couldn’t load departments">{errorMessage(access.error)}</Notice>}
        {access.data && !departments.length && (
          <Notice title="No departments available">
            You can raise openings for departments or teams you head, lead or manage. Ask HR to set you as the head, lead or PM of your unit.
          </Notice>
        )}

        <Section title="Role">
          <div>
            <label className="label" htmlFor="op-title">Job title</label>
            <input id="op-title" className="input" maxLength={150} autoFocus placeholder="e.g. Senior Backend Engineer"
              value={form.title} onChange={(e) => set("title")(e.target.value)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="op-unit">Department / team</label>
              <select id="op-unit" className="input" value={form.orgUnitId}
                onChange={(e) => setForm((f) => ({ ...f, orgUnitId: e.target.value, locationId: "" }))}>
                <option value="">{access.isPending ? "Loading…" : "Choose…"}</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}{d.detail ? ` — ${d.detail}` : ""}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="op-job">Designation <span className="font-normal text-fg-subtle">(optional)</span></label>
              <select id="op-job" className="input" value={form.jobId} onChange={(e) => set("jobId")(e.target.value)}>
                <option value="">Not specified</option>
                {(access.data?.jobs ?? []).map((j) => <option key={j.id} value={j.id}>{j.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="op-loc">Location <span className="font-normal text-fg-subtle">(optional)</span></label>
              <select id="op-loc" className="input" value={form.locationId} onChange={(e) => set("locationId")(e.target.value)}>
                <option value="">Not specified</option>
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="op-mgr">Hiring manager</label>
              <select id="op-mgr" className="input" value={form.managerId} onChange={(e) => set("managerId")(e.target.value)}>
                <option value="">{editing ? "Unchanged / requester" : "Me (requester)"}</option>
                {editing && opening!.hiring_manager_employment_id && opening!.hiring_manager_name
                  && !(access.data?.hiring_managers ?? []).some((m) => m.id === opening!.hiring_manager_employment_id) && (
                  <option value={opening!.hiring_manager_employment_id}>{opening!.hiring_manager_name}</option>
                )}
                {(access.data?.hiring_managers ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.detail ? ` · ${m.detail}` : ""}</option>)}
              </select>
            </div>
          </div>
        </Section>

        <Section title="Position">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="label" htmlFor="op-type">Employment type</label>
              <select id="op-type" className="input" value={form.employmentType} onChange={(e) => set("employmentType")(e.target.value as EmploymentType)}>
                {Object.entries(EMPLOYMENT_TYPES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="op-mode">Work mode</label>
              <select id="op-mode" className="input" value={form.workMode} onChange={(e) => set("workMode")(e.target.value as WorkMode)}>
                {Object.entries(WORK_MODES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="op-pos">Positions</label>
              <input id="op-pos" type="number" min={1} max={500} className="input" value={form.positions}
                onChange={(e) => set("positions")(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="op-priority">Priority</label>
              <select id="op-priority" className="input" value={form.priority} onChange={(e) => set("priority")(e.target.value as Priority)}>
                {Object.entries(PRIORITY).map(([v, p]) => <option key={v} value={v}>{p.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="op-reason">Reason</label>
              <select id="op-reason" className="input" value={form.reason} onChange={(e) => set("reason")(e.target.value as OpeningReason)}>
                {Object.entries(REASONS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="op-date">Target start date</label>
              <input id="op-date" type="date" className="input" value={form.targetDate} onChange={(e) => set("targetDate")(e.target.value)} />
            </div>
          </div>
          {form.reason === "REPLACEMENT" && (
            <div>
              <label className="label" htmlFor="op-repl">Replacing</label>
              <input id="op-repl" className="input" maxLength={150} placeholder="Name of the person leaving"
                value={form.replacementFor} onChange={(e) => set("replacementFor")(e.target.value)} />
            </div>
          )}
        </Section>

        <Section title="Experience & budget" description="Budget is visible to HR, approvers and the hiring team only.">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <span className="label">Experience (years)</span>
              <div className="flex items-center gap-2">
                <input aria-label="Minimum experience" type="number" min={0} max={60} step={0.5} className="input" placeholder="Min"
                  value={form.minExp} onChange={(e) => set("minExp")(e.target.value)} />
                <span className="text-fg-subtle">–</span>
                <input aria-label="Maximum experience" type="number" min={0} max={60} step={0.5} className="input" placeholder="Max"
                  value={form.maxExp} onChange={(e) => set("maxExp")(e.target.value)} />
              </div>
            </div>
            <div>
              <span className="label">Annual salary budget</span>
              <div className="flex items-center gap-2">
                <input aria-label="Currency" className="input w-20 shrink-0 font-mono uppercase" maxLength={3}
                  value={form.currency} onChange={(e) => set("currency")(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))} />
                <input aria-label="Minimum salary" type="number" min={0} step={1000} className="input" placeholder="Min"
                  value={form.salaryMin} onChange={(e) => set("salaryMin")(e.target.value)} />
                <span className="text-fg-subtle">–</span>
                <input aria-label="Maximum salary" type="number" min={0} step={1000} className="input" placeholder="Max"
                  value={form.salaryMax} onChange={(e) => set("salaryMax")(e.target.value)} />
              </div>
            </div>
          </div>
        </Section>

        <Section title="Job description">
          <div>
            <label className="label" htmlFor="op-desc">About the role</label>
            <textarea id="op-desc" className="input" rows={5} maxLength={20000}
              placeholder="What the person will own, the team they join and why the role exists."
              value={form.description} onChange={(e) => set("description")(e.target.value)} />
            {form.description.trim().length > 0 && form.description.trim().length < 10 && (
              <p className="hint">Write at least a sentence.</p>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="op-resp">Responsibilities <span className="font-normal text-fg-subtle">(optional)</span></label>
              <textarea id="op-resp" className="input" rows={5} maxLength={20000} placeholder="One per line"
                value={form.responsibilities} onChange={(e) => set("responsibilities")(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="op-req">Requirements <span className="font-normal text-fg-subtle">(optional)</span></label>
              <textarea id="op-req" className="input" rows={5} maxLength={20000} placeholder="One per line"
                value={form.requirements} onChange={(e) => set("requirements")(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="op-skills">Key skills</label>
            <TagInput id="op-skills" value={form.skills} onChange={set("skills")} placeholder="Type a skill and press Enter" />
          </div>
        </Section>

        {problems.length > 0 && (
          <ul className="space-y-1 text-xs font-medium text-danger">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        )}
      </form>
    </Sheet>
  );
}

import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Briefcase, Clock, Download, Eye, FileText, Mail, MapPin, MessageSquare, Pencil, Phone, Star, Trash2, UserRoundCheck,
} from "lucide-react";
import { Sheet, ConfirmDialog } from "../ui/Overlay";
import { Avatar } from "../ui/Avatar";
import { Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { recruitmentApi } from "../../api/recruitment";
import type { ApplicationDetail, Stage } from "../../api/recruitment";
import { AddEmployeeSheet } from "../../pages/EmployeePage";
import { LINK_TYPES, SOURCES, STAGE_DOT, daysSince, money, years } from "./meta";
import { LinkIcon } from "./LinkIcon";
import { ActivityList, MoveReasonDialog } from "./activity";
import { CandidateFormSheet } from "./CandidateFormSheet";
import { ResumeViewer } from "./ResumeViewer";
import { downloadResume } from "./resume";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px] font-medium text-fg">{children ?? <span className="font-normal text-fg-subtle">—</span>}</dd>
    </div>
  );
}

function Stars({ value, onChange, disabled }: { value: number | null; onChange?: (v: number | null) => void; disabled?: boolean }) {
  return (
    <div className="flex items-center gap-0.5" role={onChange ? "radiogroup" : undefined} aria-label="Rating">
      {[1, 2, 3, 4, 5].map((n) => {
        const on = (value ?? 0) >= n;
        const star = <Star size={15} className={on ? "fill-warning text-warning" : "text-line-strong"} />;
        return onChange ? (
          <button key={n} type="button" disabled={disabled} className="rounded p-0.5 hover:bg-muted disabled:opacity-60"
            aria-label={`${n} star${n > 1 ? "s" : ""}`} aria-checked={value === n} role="radio"
            onClick={() => onChange(value === n ? null : n)}>
            {star}
          </button>
        ) : <span key={n} className="p-0.5">{star}</span>;
      })}
    </div>
  );
}

/** One candidate in one opening: profile, resume, stage, feedback and history. */
export function ApplicationSheet({ applicationId, stages, onClose }: {
  applicationId: string | null;
  stages: Stage[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState("");
  const [reasonStage, setReasonStage] = useState<Stage | null>(null);
  const [viewing, setViewing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [hiring, setHiring] = useState(false);
  const [removingResume, setRemovingResume] = useState(false);

  const detail = useQuery({
    queryKey: ["recruitment-application", applicationId],
    queryFn: () => recruitmentApi.application(applicationId!),
    enabled: !!applicationId,
  });
  const app = detail.data;

  const refresh = (next?: ApplicationDetail) => {
    if (next) qc.setQueryData(["recruitment-application", next.id], next);
    qc.invalidateQueries({ queryKey: ["recruitment-applications"] });
    qc.invalidateQueries({ queryKey: ["recruitment-opening"] });
    qc.invalidateQueries({ queryKey: ["recruitment-openings"] });
    qc.invalidateQueries({ queryKey: ["recruitment-events"] });
    qc.invalidateQueries({ queryKey: ["recruitment-candidates"] });
  };

  const move = useMutation({
    mutationFn: ({ stage, reason }: { stage: Stage; reason: string | null }) =>
      recruitmentApi.moveApplication(app!.id, stage.id, reason, app!.version),
    onSuccess: (next) => { refresh(next); setReasonStage(null); toast.success(`Moved to ${next.stage_name}`); },
    onError: (e) => toast.error("Couldn’t move the candidate", errorMessage(e)),
  });
  const rate = useMutation({
    mutationFn: (rating: number | null) => recruitmentApi.rateApplication(app!.id, rating),
    onSuccess: (next) => refresh(next),
    onError: (e) => toast.error("Couldn’t save the rating", errorMessage(e)),
  });
  const addNote = useMutation({
    mutationFn: () => recruitmentApi.addNote(app!.id, note.trim()),
    onSuccess: (next) => { refresh(next); setNote(""); toast.success("Feedback added"); },
    onError: (e) => toast.error("Couldn’t add feedback", errorMessage(e)),
  });
  const removeResume = useMutation({
    mutationFn: () => recruitmentApi.deleteResume(app!.candidate.id),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["recruitment-application"] }); setRemovingResume(false); toast.success("Resume removed"); },
    onError: (e) => toast.error("Couldn’t remove the resume", errorMessage(e)),
  });

  const pick = (stageId: string) => {
    const stage = stages.find((s) => s.id === stageId);
    if (!stage || !app || stage.id === app.stage_id) return;
    if (stage.category === "REJECTED" || stage.category === "WITHDRAWN") setReasonStage(stage);
    else move.mutate({ stage, reason: null });
  };

  const c = app?.candidate;
  const live = app && ["OPEN", "ON_HOLD", "FILLED"].includes(app.opening_status);
  const canMove = app?.can_manage && live && !app.hired_employment_id;
  const activeStages = stages.filter((s) => s.is_active || s.id === app?.stage_id);
  const currentStage = stages.find((s) => s.id === app?.stage_id);

  return (
    <>
      <Sheet
        open={!!applicationId}
        onClose={onClose}
        className="max-w-2xl"
        title={c?.full_name ?? "Candidate"}
        description={app ? `${app.opening_code} · ${app.opening_title}` : undefined}
        footer={app?.can_manage ? (
          <>
            <button type="button" className="btn-secondary" onClick={() => setEditing(true)}><Pencil size={13} /> Edit candidate</button>
            <button type="button" className="btn-primary" onClick={onClose}>Done</button>
          </>
        ) : undefined}
      >
        {detail.isPending ? (
          <div className="space-y-4"><Skeleton className="h-20 rounded-xl" /><Skeleton className="h-40 rounded-xl" /><Skeleton className="h-40 rounded-xl" /></div>
        ) : detail.isError || !app || !c ? (
          <Notice title="Couldn’t load this candidate">{errorMessage(detail.error)}</Notice>
        ) : (
          <div className="space-y-6">
            {/* ── Header ─────────────────────────────────────────────── */}
            <div className="flex items-start gap-4">
              <Avatar name={c.full_name} size="lg" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] text-fg-muted">
                  {[c.current_title, c.current_company && `at ${c.current_company}`].filter(Boolean).join(" ") || "No current role recorded"}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-subtle">
                  {c.location && <span className="inline-flex items-center gap-1"><MapPin size={12} />{c.location}</span>}
                  {c.total_experience_years && <span className="inline-flex items-center gap-1"><Briefcase size={12} />{years(c.total_experience_years)}</span>}
                  <span className="inline-flex items-center gap-1"><Clock size={12} />In stage {daysSince(app.stage_changed_at)}</span>
                </div>
              </div>
              <Stars value={app.rating} onChange={app.can_manage ? (v) => rate.mutate(v) : undefined} disabled={rate.isPending} />
            </div>

            {/* ── Stage ──────────────────────────────────────────────── */}
            <section className="rounded-xl border border-line p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${currentStage ? STAGE_DOT[currentStage.color] : "bg-fg-subtle"}`} />
                  <span className="text-[13px] font-semibold text-fg">{app.stage_name}</span>
                  <span className="text-xs text-fg-subtle">since {format(new Date(app.stage_changed_at), "d MMM yyyy")}</span>
                </div>
                {canMove && (
                  <select aria-label="Move to stage" className="input h-8 w-auto min-w-[11rem] text-xs" value={app.stage_id}
                    disabled={move.isPending} onChange={(e) => pick(e.target.value)}>
                    {activeStages.map((s) => <option key={s.id} value={s.id}>{s.id === app.stage_id ? `${s.name} (current)` : `Move to ${s.name}`}</option>)}
                  </select>
                )}
              </div>
              {app.outcome_reason && <p className="mt-2 text-[13px] text-fg-muted"><span className="font-medium text-fg">Reason:</span> {app.outcome_reason}</p>}
              {app.stage_category === "HIRED" && (
                app.hired_employment_id ? (
                  <div className="mt-3 flex items-center justify-between gap-3 rounded-lg bg-success/[0.07] px-3 py-2.5 text-[13px]">
                    <span className="inline-flex items-center gap-2 font-medium text-success"><UserRoundCheck size={15} /> Employee record created</span>
                    {app.can_manage && <Link className="link text-xs" to={`/employees?id=${app.hired_employment_id}`}>Open employee</Link>}
                  </div>
                ) : app.can_hire ? (
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-brand-500/[0.06] px-3 py-2.5">
                    <span className="text-[13px] text-fg-muted">Ready to join? Create their employee record and start onboarding.</span>
                    <button type="button" className="btn-primary btn-sm" onClick={() => setHiring(true)}><UserRoundCheck size={13} /> Create employee</button>
                  </div>
                ) : null
              )}
              {!live && <p className="mt-2 text-xs text-fg-subtle">The opening is {app.opening_status.toLowerCase().replace("_", " ")} — reopen it to move candidates.</p>}
            </section>

            {/* ── Contact & links ────────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="eyebrow">Contact & profiles</h3>
              <div className="flex flex-wrap gap-2">
                {c.email && <a className="btn-secondary btn-sm" href={`mailto:${c.email}`}><Mail size={13} /> {c.email}</a>}
                {c.phone && <a className="btn-secondary btn-sm" href={`tel:${c.phone.replace(/\s/g, "")}`}><Phone size={13} /> {c.phone}</a>}
                {c.links.map((l) => (
                  <a key={l.url} className="btn-secondary btn-sm" href={l.url} target="_blank" rel="noopener noreferrer nofollow" title={l.url}>
                    <LinkIcon type={l.type} size={13} /> {l.label || LINK_TYPES[l.type]}
                  </a>
                ))}
                {!c.email && !c.phone && !c.links.length && <p className="text-[13px] text-fg-subtle">No contact details or links.</p>}
              </div>
            </section>

            {/* ── Details ────────────────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="eyebrow">Details</h3>
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
                <Fact label="Experience">{c.total_experience_years ? years(c.total_experience_years) : null}</Fact>
                <Fact label="Notice period">{c.notice_period_days !== null ? `${c.notice_period_days} days` : null}</Fact>
                <Fact label="Source">{SOURCES[c.source]}{c.source_detail ? ` · ${c.source_detail}` : ""}</Fact>
                {app.can_manage && <Fact label="Current CTC">{money(c.current_ctc)}</Fact>}
                {app.can_manage && <Fact label="Expected CTC">{money(c.expected_ctc)}</Fact>}
                <Fact label="Applied">{format(new Date(app.applied_at), "d MMM yyyy")}</Fact>
              </dl>
              {c.skills.length > 0 && (
                <div className="flex flex-wrap gap-1.5">{c.skills.map((s) => <span key={s} className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-fg">{s}</span>)}</div>
              )}
              {c.summary && <p className="whitespace-pre-line text-[13px] leading-relaxed text-fg-muted">{c.summary}</p>}
            </section>

            {/* ── Resume ─────────────────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="eyebrow">Resume</h3>
              {c.resume ? (
                <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-4 py-3">
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-500/10 text-accent"><FileText size={16} /></div>
                  <div className="min-w-0 flex-1 basis-40">
                    <p className="truncate text-[13px] font-medium text-fg">{c.resume.file_name}</p>
                    <p className="text-xs text-fg-subtle">{Math.max(1, Math.round(c.resume.size / 1024))} KB · uploaded {format(new Date(c.resume.uploaded_at), "d MMM yyyy")}</p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button type="button" className="btn-secondary btn-sm" onClick={() => setViewing(true)}><Eye size={13} /> View</button>
                    <button type="button" className="btn-icon" title="Download" aria-label="Download resume"
                      onClick={() => downloadResume(c).catch((e) => toast.error("Download failed", errorMessage(e)))}><Download size={14} /></button>
                    {app.can_manage && (
                      <button type="button" className="btn-icon hover:text-danger" title="Remove" aria-label="Remove resume" onClick={() => setRemovingResume(true)}><Trash2 size={14} /></button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-dashed border-line px-4 py-3 text-[13px] text-fg-subtle">
                  No resume uploaded.
                  {app.can_manage && <button type="button" className="btn-secondary btn-sm" onClick={() => setEditing(true)}>Upload resume</button>}
                </div>
              )}
            </section>

            {app.other_applications.length > 0 && (
              <section className="space-y-2">
                <h3 className="eyebrow">Also in</h3>
                <ul className="divide-y divide-line rounded-xl border border-line">
                  {app.other_applications.map((o) => (
                    <li key={o.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-[13px]">
                      <Link to={`/recruitment/openings/${o.opening_id}`} className="link truncate">{o.opening_code} · {o.opening_title}</Link>
                      <span className="shrink-0 text-xs text-fg-subtle">{o.stage_name}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* ── Feedback & history ─────────────────────────────────── */}
            <section className="space-y-3">
              <h3 className="eyebrow">Feedback</h3>
              <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (note.trim()) addNote.mutate(); }}>
                <textarea className="input" rows={3} maxLength={5000} aria-label="Feedback"
                  placeholder="Interview feedback, concerns or next steps for the hiring team…"
                  value={note} onChange={(e) => setNote(e.target.value)} />
                <div className="flex justify-end">
                  <button type="submit" className="btn-secondary btn-sm" disabled={!note.trim() || addNote.isPending}>
                    <MessageSquare size={13} /> {addNote.isPending ? "Adding…" : "Add feedback"}
                  </button>
                </div>
              </form>
              <ActivityList events={app.events} />
            </section>
          </div>
        )}
      </Sheet>

      {app && (
        <MoveReasonDialog
          stage={reasonStage}
          candidateName={app.candidate.full_name}
          pending={move.isPending}
          onCancel={() => setReasonStage(null)}
          onConfirm={(reason) => reasonStage && move.mutate({ stage: reasonStage, reason })}
        />
      )}
      {viewing && c?.resume && <ResumeViewer candidate={c} onClose={() => setViewing(false)} />}
      {app && (
        <CandidateFormSheet open={editing} onClose={() => setEditing(false)} candidate={app.candidate} showPay={app.can_manage} />
      )}
      <ConfirmDialog
        open={removingResume}
        onClose={() => setRemovingResume(false)}
        onConfirm={() => removeResume.mutate()}
        title="Remove the resume?"
        description="The file is deleted. You can upload a new one at any time."
        confirmLabel="Remove"
        loading={removeResume.isPending}
      />
      {app?.hire_defaults && (
        <AddEmployeeSheet
          open={hiring}
          onClose={() => setHiring(false)}
          title={`Create employee — ${app.candidate.full_name}`}
          initial={{
            first: app.hire_defaults.first_name,
            last: app.hire_defaults.last_name,
            entity: app.hire_defaults.legal_entity_id,
            orgUnitId: app.hire_defaults.org_unit_id,
            jobId: app.hire_defaults.job_id ?? "",
            locationId: app.hire_defaults.location_id ?? "",
            managerEmploymentId: app.hire_defaults.manager_employment_id ?? "",
            hireDate: app.hire_defaults.hire_date ?? undefined,
          }}
          onHired={async (employmentId) => refresh(await recruitmentApi.linkHire(app.id, employmentId))}
        />
      )}
    </>
  );
}

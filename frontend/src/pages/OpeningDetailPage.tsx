import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  ArrowLeft, Building2, CalendarClock, Check, ClipboardCheck, Columns3, List, MapPin, MoreHorizontal, Pause, Pencil, Play,
  Search, Send, Trash2, Undo2, UserPlus, Users, XCircle,
} from "lucide-react";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Tabs, Segmented } from "../components/ui/Tabs";
import { ConfirmDialog, Dialog } from "../components/ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { usePopover } from "../components/ui/Popover";
import { useToast, errorMessage } from "../components/ui/Toast";
import { recruitmentApi } from "../api/recruitment";
import type { Application, OpeningDetail, Stage } from "../api/recruitment";
import { EMPLOYMENT_TYPES, OPENING_STATUS, PRIORITY, REASONS, STAGE_DOT, WORK_MODES, daysSince, money, range, years } from "../components/recruitment/meta";
import { OpeningFormSheet } from "../components/recruitment/OpeningFormSheet";
import { CandidateFormSheet } from "../components/recruitment/CandidateFormSheet";
import { ApplicationSheet } from "../components/recruitment/ApplicationSheet";
import { PipelineBoard } from "../components/recruitment/PipelineBoard";
import { ActivityList, MoveReasonDialog } from "../components/recruitment/activity";

type DetailTab = "pipeline" | "details" | "activity";

function Meta({ icon: Icon, children }: { icon: typeof Building2; children: ReactNode }) {
  return <span className="inline-flex items-center gap-1.5"><Icon size={13} className="text-fg-subtle" />{children}</span>;
}

function DetailBlock({ title, text }: { title: string; text: string | null }) {
  if (!text) return null;
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const asList = lines.length > 1;
  return (
    <section className="space-y-2">
      <h3 className="eyebrow">{title}</h3>
      {asList ? (
        <ul className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-fg-muted">{lines.map((l, i) => <li key={i}>{l.replace(/^[-•*]\s*/, "")}</li>)}</ul>
      ) : (
        <p className="whitespace-pre-line text-[13px] leading-relaxed text-fg-muted">{text}</p>
      )}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 text-[13px] font-medium text-fg">{children || <span className="font-normal text-fg-subtle">—</span>}</dd>
    </div>
  );
}

export function OpeningDetailPage() {
  const { openingId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const requestedTab = (["pipeline", "details", "activity"].includes(params.get("tab") ?? "") ? params.get("tab") : "pipeline") as DetailTab;
  const setTab = (t: DetailTab) => { const next = new URLSearchParams(params); if (t === "pipeline") next.delete("tab"); else next.set("tab", t); setParams(next, { replace: true }); };
  const [view, setView] = useState<"board" | "list">("board");
  // Pipeline filters: no stage selected = every stage.
  const [stageFilter, setStageFilter] = useState<string[]>([]);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [openApp, setOpenApp] = useState<string | null>(params.get("application"));
  const [decision, setDecision] = useState<"APPROVE" | "REJECT" | null>(null);
  const [comment, setComment] = useState("");
  const [statusChange, setStatusChange] = useState<"ON_HOLD" | "CLOSED" | null>(null);
  const [statusReason, setStatusReason] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [pendingMove, setPendingMove] = useState<{ app: Application; stage: Stage } | null>(null);
  const { open: menuOpen, setOpen: setMenuOpen, ref: menuRef } = usePopover<HTMLDivElement>();

  const opening = useQuery({ queryKey: ["recruitment-opening", openingId], queryFn: () => recruitmentApi.opening(openingId), retry: false });
  const stages = useQuery({ queryKey: ["recruitment-stages"], queryFn: recruitmentApi.stages });
  const live = !!opening.data && ["OPEN", "ON_HOLD", "FILLED", "CLOSED"].includes(opening.data.status);
  // Before approval there is no pipeline yet, so the job description is the first tab.
  const tab: DetailTab = !live && requestedTab === "pipeline" ? "details" : requestedTab;
  const applications = useQuery({
    queryKey: ["recruitment-applications", openingId],
    queryFn: () => recruitmentApi.applications(openingId),
    enabled: live,
  });
  const events = useQuery({
    queryKey: ["recruitment-events", openingId],
    queryFn: () => recruitmentApi.openingEvents(openingId),
    enabled: tab === "activity" && !!opening.data,
  });

  const afterChange = (next: OpeningDetail, message: string) => {
    qc.setQueryData(["recruitment-opening", next.id], next);
    qc.invalidateQueries({ queryKey: ["recruitment-openings"] });
    qc.invalidateQueries({ queryKey: ["recruitment-events", next.id] });
    qc.invalidateQueries({ queryKey: ["approval-inbox"] });
    toast.success(message);
  };
  const submit = useMutation({
    mutationFn: () => recruitmentApi.submitOpening(openingId),
    onSuccess: (o) => afterChange(o, o.status === "OPEN" ? "Opening published" : "Sent for approval"),
    onError: (e) => toast.error("Couldn’t submit the opening", errorMessage(e)),
  });
  const withdraw = useMutation({
    mutationFn: () => recruitmentApi.withdrawOpening(openingId),
    onSuccess: (o) => afterChange(o, "Withdrawn — it’s a draft again"),
    onError: (e) => toast.error("Couldn’t withdraw the opening", errorMessage(e)),
  });
  const decide = useMutation({
    mutationFn: () => recruitmentApi.decideOpening(openingId, decision!, comment.trim()),
    onSuccess: (o) => {
      setDecision(null); setComment("");
      afterChange(o, o.status === "OPEN" ? "Opening approved" : o.status === "REJECTED" ? "Opening rejected" : "Approved — sent to the next stage");
    },
    onError: (e) => toast.error("Couldn’t record the decision", errorMessage(e)),
  });
  const setStatus = useMutation({
    mutationFn: (status: "OPEN" | "ON_HOLD" | "CLOSED") => recruitmentApi.setOpeningStatus(openingId, status, statusReason.trim()),
    onSuccess: (o) => {
      setStatusChange(null); setStatusReason("");
      afterChange(o, o.status === "OPEN" ? "Opening reopened" : o.status === "ON_HOLD" ? "Opening put on hold" : "Opening closed");
    },
    onError: (e) => toast.error("Couldn’t change the status", errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => recruitmentApi.deleteOpening(openingId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["recruitment-openings"] }); toast.success("Opening deleted"); navigate("/recruitment"); },
    onError: (e) => toast.error("Couldn’t delete the opening", errorMessage(e)),
  });
  const move = useMutation({
    mutationFn: ({ app, stage, reason }: { app: Application; stage: Stage; reason: string | null }) =>
      recruitmentApi.moveApplication(app.id, stage.id, reason, app.version),
    onMutate: async ({ app, stage }) => {
      // Move the card straight away; roll back if the server refuses.
      const key = ["recruitment-applications", openingId];
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<Application[]>(key);
      qc.setQueryData<Application[]>(key, (list) => list?.map((a) => (a.id === app.id ? { ...a, stage_id: stage.id, stage_name: stage.name, stage_category: stage.category } : a)));
      return { previous };
    },
    onError: (e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(["recruitment-applications", openingId], ctx.previous);
      toast.error("Couldn’t move the candidate", errorMessage(e));
    },
    onSuccess: (next) => {
      setPendingMove(null);
      qc.setQueryData(["recruitment-application", next.id], next);
      toast.success(`${next.candidate.full_name} → ${next.stage_name}`);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["recruitment-applications", openingId] });
      qc.invalidateQueries({ queryKey: ["recruitment-opening", openingId] });
      qc.invalidateQueries({ queryKey: ["recruitment-openings"] });
    },
  });

  const requestMove = (app: Application, stage: Stage) => {
    if (stage.category === "REJECTED" || stage.category === "WITHDRAWN") setPendingMove({ app, stage });
    else move.mutate({ app, stage, reason: null });
  };

  if (opening.isPending) {
    return <div className="space-y-4"><Skeleton className="h-8 w-48" /><Skeleton className="h-28 rounded-xl" /><Skeleton className="h-80 rounded-xl" /></div>;
  }
  if (opening.isError || !opening.data) {
    return (
      <div className="card">
        <EmptyState icon={ClipboardCheck} title="Opening not found" description="It may have been deleted, or you don’t have access to it."
          action={<Link to="/recruitment" className="btn-secondary btn-sm"><ArrowLeft size={13} /> Back to recruitment</Link>} />
      </div>
    );
  }

  const o = opening.data;
  const status = OPENING_STATUS[o.status];
  const allStages = stages.data ?? [];
  const apps = applications.data ?? [];
  const query = candidateQuery.trim().toLowerCase();
  const filtering = stageFilter.length > 0 || query.length > 0;
  const visibleApps = apps.filter((a) => {
    if (stageFilter.length && !stageFilter.includes(a.stage_id)) return false;
    if (!query) return true;
    const c = a.candidate;
    return [c.full_name, c.email, c.phone, c.current_title, c.current_company, c.location, ...c.skills]
      .some((v) => v?.toLowerCase().includes(query));
  });
  const boardStages = stageFilter.length ? allStages.filter((s) => stageFilter.includes(s.id)) : allStages;
  const toggleStage = (id: string) =>
    setStageFilter((current) => (current.includes(id) ? current.filter((s) => s !== id) : [...current, id]));
  const clearFilters = () => { setStageFilter([]); setCandidateQuery(""); };
  const salary = range(o.salary_min, o.salary_max, (v) => money(v, o.currency) ?? v);
  const experience = range(o.min_experience_years, o.max_experience_years, years);
  const canMove = o.can_manage && ["OPEN", "ON_HOLD", "FILLED"].includes(o.status);
  const progress = Math.min(100, Math.round((o.hired / Math.max(o.positions, 1)) * 100));

  const menuItems: { label: string; icon: typeof Pause; onClick: () => void; danger?: boolean }[] = [];
  if (o.can_manage && o.status === "OPEN") menuItems.push({ label: "Put on hold", icon: Pause, onClick: () => setStatusChange("ON_HOLD") });
  if (o.can_manage && ["OPEN", "ON_HOLD", "FILLED"].includes(o.status)) menuItems.push({ label: "Close opening", icon: XCircle, onClick: () => setStatusChange("CLOSED"), danger: true });
  if (o.can_submit) menuItems.push({ label: "Delete", icon: Trash2, onClick: () => setDeleting(true), danger: true });

  return (
    <div>
      <Link to="/recruitment" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-fg-muted hover:text-fg"><ArrowLeft size={14} /> Recruitment</Link>

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-fg-subtle">{o.code}</span>
            <StatusBadge tone={status.tone} label={status.label} />
            <StatusBadge tone={PRIORITY[o.priority].tone} label={`${PRIORITY[o.priority].label} priority`} dot={false} />
          </div>
          <h1 className="mt-1 text-[22px] font-semibold leading-tight tracking-tight text-fg">{o.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-fg-muted">
            <Meta icon={Building2}>{o.org_unit_name}{o.legal_entity_name ? ` · ${o.legal_entity_name}` : ""}</Meta>
            {o.location_name && <Meta icon={MapPin}>{o.location_name} · {WORK_MODES[o.work_mode]}</Meta>}
            <Meta icon={Users}>{o.positions} position{o.positions === 1 ? "" : "s"} · {EMPLOYMENT_TYPES[o.employment_type]}</Meta>
            {o.target_start_date && <Meta icon={CalendarClock}>Start by {format(new Date(`${o.target_start_date}T00:00:00`), "d MMM yyyy")}</Meta>}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {o.can_edit && <button type="button" className="btn-secondary" onClick={() => setEditing(true)}><Pencil size={14} /> Edit</button>}
          {o.can_withdraw && <button type="button" className="btn-secondary" disabled={withdraw.isPending} onClick={() => withdraw.mutate()}><Undo2 size={14} /> Withdraw</button>}
          {o.can_submit && <button type="button" className="btn-primary" disabled={submit.isPending} onClick={() => submit.mutate()}><Send size={14} /> {submit.isPending ? "Submitting…" : "Submit for approval"}</button>}
          {o.can_decide && (
            <>
              <button type="button" className="btn-danger-soft" onClick={() => setDecision("REJECT")}><XCircle size={14} /> Reject</button>
              <button type="button" className="btn-primary" onClick={() => setDecision("APPROVE")}><Check size={14} /> Approve</button>
            </>
          )}
          {o.can_manage && (o.status === "ON_HOLD" || o.status === "CLOSED" || o.status === "FILLED") && (
            <button type="button" className="btn-secondary" disabled={setStatus.isPending} onClick={() => setStatus.mutate("OPEN")}><Play size={14} /> Reopen</button>
          )}
          {o.can_manage && o.status === "OPEN" && (
            <button type="button" className="btn-primary" onClick={() => setAdding(true)}><UserPlus size={14} /> Add candidate</button>
          )}
          {menuItems.length > 0 && (
            <div className="relative" ref={menuRef}>
              <button type="button" className="btn-icon h-9 w-9 border border-line" aria-label="More actions" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>
                <MoreHorizontal size={16} />
              </button>
              {menuOpen && (
                <div className="popover absolute right-0 top-11 w-48">
                  {menuItems.map((m) => (
                    <button key={m.label} type="button" className={`menu-item ${m.danger ? "hover:text-danger" : ""}`} onClick={() => { setMenuOpen(false); m.onClick(); }}>
                      <m.icon size={14} /> {m.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Status banners ───────────────────────────────────────────────── */}
      <div className="mb-5 space-y-3">
        {o.status === "DRAFT" && (
          <Notice tone="info" title="This opening is a draft">Only you and recruiters can see it. Submit it for approval when the details are final.</Notice>
        )}
        {o.status === "PENDING_APPROVAL" && (
          <Notice tone="info" title="Awaiting approval"
            action={o.approval_mode === "FLOW" && o.approval_instance_id ? <Link to="/approvals" className="btn-secondary btn-sm shrink-0">Open approvals</Link> : undefined}>
            {o.approval_mode === "FLOW" ? "Routed through the approval flow configured for this team." : "An HR approver for this company needs to sign it off."}
            {o.submitted_at && ` Submitted ${format(new Date(o.submitted_at), "d MMM yyyy")}.`}
          </Notice>
        )}
        {o.status === "REJECTED" && (
          <Notice title="This opening was rejected">{o.decision_comment || "No reason was given."} Edit it and submit again if the role is still needed.</Notice>
        )}
        {(o.status === "ON_HOLD" || o.status === "CLOSED") && o.close_reason && (
          <Notice tone="info" title={o.status === "ON_HOLD" ? "On hold" : "Closed"}>{o.close_reason}</Notice>
        )}
      </div>

      {/* ── Summary strip ────────────────────────────────────────────────── */}
      {live && (
        <div className="card mb-5 grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-xs text-fg-subtle">Hired</p>
            <p className="mt-0.5 text-lg font-semibold tabular-nums text-fg">{o.hired} <span className="text-sm font-normal text-fg-subtle">/ {o.positions}</span></p>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-success" style={{ width: `${progress}%` }} /></div>
          </div>
          <div><p className="text-xs text-fg-subtle">In pipeline</p><p className="mt-0.5 text-lg font-semibold tabular-nums text-fg">{o.in_progress}</p><p className="text-xs text-fg-subtle">{o.candidates} candidate{o.candidates === 1 ? "" : "s"} in total</p></div>
          <div><p className="text-xs text-fg-subtle">Hiring manager</p><p className="mt-0.5 truncate text-[13px] font-medium text-fg">{o.hiring_manager_name ?? "—"}</p><p className="truncate text-xs text-fg-subtle">Raised by {o.requested_by_name ?? "—"}</p></div>
          <div><p className="text-xs text-fg-subtle">Open for</p><p className="mt-0.5 text-[13px] font-medium text-fg">{o.approved_at ? daysSince(o.approved_at) : "—"}</p><p className="text-xs text-fg-subtle">{o.approved_by_name ? `Approved by ${o.approved_by_name}` : ""}</p></div>
        </div>
      )}

      <Tabs<DetailTab>
        className="mb-5"
        value={tab}
        onChange={setTab}
        items={[
          ...(live ? [{ value: "pipeline" as const, label: "Pipeline", count: apps.length }] : []),
          { value: "details", label: "Job details" },
          { value: "activity", label: "Activity" },
        ]}
      />

      {tab === "pipeline" && live ? (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-1 flex-wrap items-center gap-1.5" role="group" aria-label="Filter by stage">
              <button type="button" aria-pressed={!stageFilter.length} onClick={() => setStageFilter([])}
                className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors ${!stageFilter.length ? "border-fg bg-fg text-surface" : "border-line text-fg-muted hover:bg-muted hover:text-fg"}`}>
                All
                <span className={`rounded-full px-1.5 text-[10px] tabular-nums ${!stageFilter.length ? "bg-surface/20" : "bg-muted"}`}>{apps.length}</span>
              </button>
              {allStages.filter((s) => s.is_active || apps.some((a) => a.stage_id === s.id)).map((s) => {
                const n = apps.filter((a) => a.stage_id === s.id).length;
                const on = stageFilter.includes(s.id);
                return (
                  <button key={s.id} type="button" aria-pressed={on} onClick={() => toggleStage(s.id)}
                    title={on ? `Hide ${s.name}` : `Show only ${s.name}${stageFilter.length ? " (added to the filter)" : ""}`}
                    className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors ${on ? "border-brand-500/50 bg-brand-500/10 text-fg" : "border-line text-fg-muted hover:bg-muted hover:text-fg"} ${n === 0 && !on ? "opacity-60" : ""}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${STAGE_DOT[s.color]}`} />
                    {s.name}
                    <span className="tabular-nums text-fg">{n}</span>
                  </button>
                );
              })}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <div className="relative w-full sm:w-56">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
                <input className="input h-8 pl-8 text-xs" placeholder="Search candidates" aria-label="Search candidates"
                  value={candidateQuery} onChange={(e) => setCandidateQuery(e.target.value)} />
              </div>
              <Segmented<"board" | "list"> value={view} onChange={setView} items={[{ value: "board", label: "Board", icon: Columns3 }, { value: "list", label: "List", icon: List }]} />
            </div>
          </div>
          {filtering && apps.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-fg-subtle">
              Showing {visibleApps.length} of {apps.length} candidate{apps.length === 1 ? "" : "s"}
              <button type="button" className="link" onClick={clearFilters}>Clear filters</button>
            </div>
          )}
          {applications.isPending || stages.isPending ? (
            <Skeleton className="h-80 rounded-xl" />
          ) : applications.isError ? (
            <Notice title="Couldn’t load candidates">{errorMessage(applications.error)}</Notice>
          ) : apps.length === 0 ? (
            <div className="card">
              <EmptyState icon={UserPlus} title="No candidates yet"
                description={o.can_manage ? (o.status === "OPEN" ? "Add the first candidate with their resume and profile links." : "Reopen the opening to add candidates.") : "HR hasn’t added candidates yet. You’ll see them here as they come in."}
                action={o.can_manage && o.status === "OPEN" ? <button type="button" className="btn-primary btn-sm" onClick={() => setAdding(true)}><UserPlus size={13} /> Add candidate</button> : undefined} />
            </div>
          ) : visibleApps.length === 0 ? (
            <div className="card">
              <EmptyState icon={Search} title="No candidates match"
                description="Try another stage or search term."
                action={<button type="button" className="btn-secondary btn-sm" onClick={clearFilters}>Clear filters</button>} />
            </div>
          ) : view === "board" ? (
            <PipelineBoard stages={boardStages} applications={visibleApps} canMove={!!canMove} onOpen={(a) => setOpenApp(a.id)} onMove={requestMove} />
          ) : (
            <div className="card overflow-x-auto">
              <table className="tbl">
                <thead><tr><th>Candidate</th><th>Stage</th><th>Experience</th><th>Rating</th><th>In stage</th><th>Applied</th></tr></thead>
                <tbody>
                  {visibleApps.map((a) => {
                    const st = allStages.find((s) => s.id === a.stage_id);
                    return (
                      <tr key={a.id} className="cursor-pointer" onClick={() => setOpenApp(a.id)}>
                        <td><p className="font-medium text-fg">{a.candidate.full_name}</p><p className="text-xs text-fg-subtle">{[a.candidate.current_title, a.candidate.current_company].filter(Boolean).join(" · ") || a.candidate.email || "—"}</p></td>
                        <td><span className="inline-flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${st ? STAGE_DOT[st.color] : "bg-fg-subtle"}`} />{a.stage_name}</span></td>
                        <td>{a.candidate.total_experience_years ? years(a.candidate.total_experience_years) : "—"}</td>
                        <td>{a.rating ? `${a.rating}/5` : "—"}</td>
                        <td>{daysSince(a.stage_changed_at)}</td>
                        <td>{format(new Date(a.applied_at), "d MMM yyyy")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!o.can_manage && apps.length > 0 && <p className="text-xs text-fg-subtle">Open a candidate to read their profile and resume and leave feedback. HR moves candidates between stages.</p>}
        </div>
      ) : tab === "activity" ? (
        <div className="card p-5">
          {events.isPending ? <Skeleton className="h-40 rounded-lg" /> : events.isError ? <Notice title="Couldn’t load activity">{errorMessage(events.error)}</Notice> : <ActivityList events={events.data ?? []} />}
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">
          <div className="card space-y-6 p-5">
            <DetailBlock title="About the role" text={o.description} />
            <DetailBlock title="Responsibilities" text={o.responsibilities} />
            <DetailBlock title="Requirements" text={o.requirements} />
            {o.skills.length > 0 && (
              <section className="space-y-2">
                <h3 className="eyebrow">Key skills</h3>
                <div className="flex flex-wrap gap-1.5">{o.skills.map((s) => <span key={s} className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-fg">{s}</span>)}</div>
              </section>
            )}
          </div>
          <dl className="card grid gap-4 p-5">
            <Fact label="Department">{o.org_unit_name}</Fact>
            <Fact label="Company">{o.legal_entity_name}</Fact>
            <Fact label="Designation">{o.job_title}</Fact>
            <Fact label="Location">{o.location_name ? `${o.location_name} · ${WORK_MODES[o.work_mode]}` : WORK_MODES[o.work_mode]}</Fact>
            <Fact label="Employment type">{EMPLOYMENT_TYPES[o.employment_type]}</Fact>
            <Fact label="Reason">{REASONS[o.reason]}{o.replacement_for ? ` — replacing ${o.replacement_for}` : ""}</Fact>
            <Fact label="Experience">{experience}</Fact>
            <Fact label="Salary budget">{salary}</Fact>
            <Fact label="Hiring manager">{o.hiring_manager_name}</Fact>
            <Fact label="Raised by">{o.requested_by_name}{o.created_at ? ` · ${format(new Date(o.created_at), "d MMM yyyy")}` : ""}</Fact>
            {o.approved_at && <Fact label="Approved">{o.approval_mode === "AUTO" ? "Published" : `By ${o.approved_by_name ?? "—"}`} · {format(new Date(o.approved_at), "d MMM yyyy")}</Fact>}
          </dl>
        </div>
      )}

      <OpeningFormSheet open={editing} onClose={() => setEditing(false)} opening={o} />
      <CandidateFormSheet open={adding} onClose={() => setAdding(false)} openingId={o.id} stages={allStages} />
      <ApplicationSheet applicationId={openApp} stages={allStages} onClose={() => {
        setOpenApp(null);
        if (params.get("application")) { const next = new URLSearchParams(params); next.delete("application"); setParams(next, { replace: true }); }
      }} />
      <MoveReasonDialog
        stage={pendingMove?.stage ?? null}
        candidateName={pendingMove?.app.candidate.full_name ?? ""}
        pending={move.isPending}
        onCancel={() => setPendingMove(null)}
        onConfirm={(reason) => pendingMove && move.mutate({ ...pendingMove, reason })}
      />

      <Dialog open={!!decision} onClose={() => setDecision(null)}>
        <form onSubmit={(e) => { e.preventDefault(); if (decision === "APPROVE" || comment.trim()) decide.mutate(); }}>
          <div className="space-y-3 p-6">
            <div>
              <h3 className="text-[15px] font-semibold text-fg">{decision === "APPROVE" ? "Approve" : "Reject"} {o.code}</h3>
              <p className="mt-0.5 text-[13px] text-fg-muted">
                {decision === "APPROVE" ? "The opening goes live (or to the next approval stage) and HR can start adding candidates." : "The requester sees your reason and can revise and resubmit."}
              </p>
            </div>
            <textarea className="input" rows={3} maxLength={1000} data-autofocus
              placeholder={decision === "APPROVE" ? "Comment (optional)" : "Reason for rejecting (required)"}
              value={comment} onChange={(e) => setComment(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 border-t border-line bg-panel px-6 py-3.5">
            <button type="button" className="btn-secondary" onClick={() => setDecision(null)}>Cancel</button>
            <button type="submit" className={decision === "APPROVE" ? "btn-primary" : "btn-danger"} disabled={decide.isPending || (decision === "REJECT" && !comment.trim())}>
              {decide.isPending ? "Saving…" : decision === "APPROVE" ? "Approve" : "Reject"}
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog open={!!statusChange} onClose={() => setStatusChange(null)}>
        <form onSubmit={(e) => { e.preventDefault(); if (statusChange && statusReason.trim()) setStatus.mutate(statusChange); }}>
          <div className="space-y-3 p-6">
            <div>
              <h3 className="text-[15px] font-semibold text-fg">{statusChange === "ON_HOLD" ? "Put the opening on hold" : "Close the opening"}</h3>
              <p className="mt-0.5 text-[13px] text-fg-muted">
                {statusChange === "ON_HOLD" ? "No new candidates can be added until it’s reopened. The pipeline is kept." : "Hiring stops. You can reopen it later; the pipeline and history are kept."}
              </p>
            </div>
            <textarea className="input" rows={2} maxLength={500} data-autofocus placeholder="Reason (required)" value={statusReason} onChange={(e) => setStatusReason(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 border-t border-line bg-panel px-6 py-3.5">
            <button type="button" className="btn-secondary" onClick={() => setStatusChange(null)}>Cancel</button>
            <button type="submit" className={statusChange === "CLOSED" ? "btn-danger" : "btn-primary"} disabled={!statusReason.trim() || setStatus.isPending}>
              {setStatus.isPending ? "Saving…" : statusChange === "ON_HOLD" ? "Put on hold" : "Close opening"}
            </button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog open={deleting} onClose={() => setDeleting(false)} onConfirm={() => remove.mutate()}
        title={`Delete ${o.code}?`} description="The draft and its history are removed permanently." confirmLabel="Delete" loading={remove.isPending} />
    </div>
  );
}

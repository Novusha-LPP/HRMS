import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { ArrowDown, ArrowUp, Plus, Trash2, Check, X, Users, Search, ClipboardCheck, Clock, Settings2, ChevronRight, ChevronLeft } from "lucide-react";
import { approvalsApi } from "../api/approvals";
import type { ApprovalFlow, ApprovalRequest, ApprovalStep, RequestType } from "../api/approvals";
import { UsageHelpButton } from "../components/ui/UsageHelpButton";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { StatusBadge } from "../components/ui/StatusBadge";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { Sheet } from "../components/ui/Overlay";
import { Tabs } from "../components/ui/Tabs";
import { Avatar } from "../components/ui/Avatar";
import { StatCard } from "../components/ui/StatCard";
import { useToast, errorMessage } from "../components/ui/Toast";

const TYPES: RequestType[] = ["LEAVE", "LEAVE_CANCELLATION", "CORRECTION", "OVERTIME", "JOB_REQUISITION", "FIELD_OVERRIDE"];
const TYPE_LABEL: Record<RequestType, string> = { LEAVE: "Leave", LEAVE_CANCELLATION: "Leave cancellation", CORRECTION: "Attendance correction", OVERTIME: "Overtime", JOB_REQUISITION: "Job opening", FIELD_OVERRIDE: "Change to an app-managed field" };
const label = (s: string) => { const text = s.toLowerCase().replaceAll("_", " "); return text.charAt(0).toUpperCase() + text.slice(1); };
const localInput = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
const displayValue = (v: unknown) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v) ? new Date(v).toLocaleString(undefined, { timeZoneName: "short" }) : String(v);
const DETAIL_LABEL: Record<string, string> = { ot_minutes: "Overtime", effective_minutes: "Working time", first_punch_in: "Check-in", last_punch_out: "Check-out", requested_punch_in: "Requested check-in", requested_punch_out: "Requested check-out", from_date: "Start date", to_date: "End date", days_requested: "Duration", cancel_reason: "Cancellation reason", code: "Opening", positions: "Positions", target_start_date: "Target start", opening_status: "Opening status", employment_type: "Employment type", work_mode: "Work mode" };
const detailValue = (field: string, value: unknown) => {
  if (field.endsWith("_minutes") && typeof value === "number") return `${Math.floor(value / 60)}h ${value % 60}m`;
  if (field === "days_requested") return `${value} ${Number(value) === 1 ? "day" : "days"}`;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  if (field === "correction_type" || field.endsWith("_status") || field === "priority" || field === "employment_type" || field === "work_mode") return label(String(value));
  return displayValue(value);
};

type DirectoryEntry = Awaited<ReturnType<typeof approvalsApi.directory>>[number];

function ApproverPicker({ entries, selected, unavailable, onChange, stage }: {
  entries: DirectoryEntry[]; selected: string[]; unavailable: Set<string>; onChange: (ids: string[]) => void; stage: number;
}) {
  const [search, setSearch] = useState("");
  const matches = entries.filter((u) => u.name.toLowerCase().includes(search.trim().toLowerCase()));
  return <div className="space-y-2">
    {!!selected.length && <div className="flex flex-wrap gap-1.5">{selected.map((id) => <span key={id} className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-line bg-muted px-2.5 py-1 text-xs text-fg">
      <span className="truncate">{entries.find((u) => u.id === id)?.name.split(" · ")[0] ?? "Unavailable account"}</span>
      <button type="button" className="shrink-0 text-fg-subtle hover:text-danger" aria-label={`Remove approver ${entries.find((u) => u.id === id)?.name ?? id} from stage ${stage}`} onClick={() => onChange(selected.filter((uid) => uid !== id))}><X size={12} /></button>
    </span>)}</div>}
    <details className="rounded-lg border border-line bg-surface">
      <summary className="cursor-pointer px-3 py-2 text-[13px] text-fg-muted">{selected.length ? "Change approvers" : "Choose approvers"}<span className="ml-2 text-xs text-fg-subtle"> {selected.length} selected</span></summary>
      <div className="border-t border-line p-2">
        <div className="relative mb-2"><Search size={14} className="absolute left-2.5 top-2.5 text-fg-subtle" /><input className="input pl-8" aria-label={`Search approvers for stage ${stage}`} placeholder="Search people or email…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <div className="max-h-44 space-y-1 overflow-y-auto">{matches.map((u) => <label key={u.id} className={`flex items-center gap-2.5 rounded-md px-2 py-2 text-[13px] ${unavailable.has(u.id) ? "opacity-40" : "cursor-pointer hover:bg-muted"}`}>
          <input type="checkbox" checked={selected.includes(u.id)} disabled={unavailable.has(u.id)} onChange={(e) => onChange(e.target.checked ? [...selected, u.id] : selected.filter((id) => id !== u.id))} />
          <Avatar name={u.name} size="xs" /><span className="min-w-0"><span className="block truncate text-fg">{u.name.split(" · ")[0]}</span>{u.name.includes(" · ") && <span className="block truncate text-xs text-fg-subtle">{u.name.split(" · ").slice(1).join(" · ")}</span>}</span>
        </label>)}{!matches.length && <p className="p-3 text-xs text-fg-subtle">No matching people.</p>}</div>
      </div>
    </details>
  </div>;
}

function FlowEditor({ initial, close }: { initial?: ApprovalFlow; close: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState<RequestType>(initial?.request_type ?? "LEAVE");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [steps, setSteps] = useState<ApprovalStep[]>(initial?.steps ?? [{ name: "Approval", approver_ids: [], approver_source: "PEOPLE" }]);
  const directory = useQuery({ queryKey: ["approval-directory"], queryFn: () => approvalsApi.directory() });
  const save = useMutation({
    mutationFn: () => approvalsApi.saveFlow({ name: name.trim(), request_type: kind, org_unit_id: null, employment_id: null, reusable: true, enabled,
      steps, version: initial?.version }, initial?.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["approval-flows"] }); close(); toast.success("Approval flow saved", "New requests use this chain. Submitted requests keep their original chain."); },
    onError: (e) => toast.error("Couldn’t save flow", errorMessage(e)),
  });
  const update = (index: number, value: Partial<ApprovalStep>) => setSteps((items) => items.map((s, i) => i === index ? { ...s, ...value } : s));
  const invalid = directory.isPending || directory.isError || !name.trim() || steps.some((s) => !s.name.trim() || !s.approver_ids.length);
  return <Sheet open onClose={close} title={initial ? "Edit approval flow" : "New approval flow"} description="Define the approval stages, then assign this workflow from employee profiles." className="max-w-2xl" footer={<>
    <button type="button" className="btn-secondary" onClick={close}>Cancel</button><button type="submit" form="approval-flow-form" className="btn-primary" disabled={save.isPending || invalid}>{save.isPending ? "Saving…" : "Save flow"}</button>
  </>}>
  <form id="approval-flow-form" className="space-y-6" onSubmit={(e) => { e.preventDefault(); if (!invalid) save.mutate(); }}>
    <section className="space-y-3"><h3 className="eyebrow">Flow details</h3>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="label sm:col-span-2">Flow name<input className="input mt-1" required maxLength={150} placeholder="e.g. Engineering leave approval" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="label">Request type<select className="input mt-1" value={kind} disabled={!!initial} onChange={(e) => setKind(e.target.value as RequestType)}>{TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select></label>

    </div>
    </section>
    <section className="space-y-3"><div><h3 className="eyebrow">Approval stages</h3><p className="mt-1 text-[13px] text-fg-subtle">One selected person approves each stage. Use different people for the next stage.</p></div>
    {directory.isError && <Notice title="Couldn’t load approvers">Reload to try again.</Notice>}
    <div className="space-y-3">
      {steps.map((step, index) => <div key={step.id ?? index}>
        <div className="rounded-xl border border-line bg-surface p-4">
          <div className="mb-2 flex items-center gap-3"><span className="badge badge-brand">{index + 1}</span>
            <input aria-label={`Stage ${index + 1} name`} className="input" required maxLength={100} value={step.name} onChange={(e) => update(index, { name: e.target.value })} />
            <button type="button" className="btn-icon" aria-label={`Remove stage ${index + 1}`} disabled={steps.length === 1} onClick={() => setSteps((items) => items.filter((_, i) => i !== index))}><Trash2 size={16} /></button>
          </div>
          {directory.isPending ? <Skeleton className="h-10" /> : <ApproverPicker entries={directory.data ?? []} selected={step.approver_ids} stage={index + 1}
            unavailable={new Set((directory.data ?? []).filter((u) => steps.some((s, i) => i !== index && s.approver_ids.some((id) => id === u.id || (!!u.employment_id && directory.data?.find((p) => p.id === id)?.employment_id === u.employment_id)))).map((u) => u.id))}
            onChange={(ids) => update(index, { approver_ids: ids })} />}
          <div className="mt-2 flex gap-2">
            <button type="button" className="btn-ghost btn-sm" disabled={index === 0} onClick={() => setSteps((items) => { const next = [...items]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next; })}><ArrowUp size={13} /> Move up</button>
            <button type="button" className="btn-ghost btn-sm" disabled={index === steps.length - 1} onClick={() => setSteps((items) => { const next = [...items]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; return next; })}><ArrowDown size={13} /> Move down</button>
          </div>
        </div>
      </div>)}
    </div>
    <button type="button" className="btn-secondary btn-sm" disabled={steps.length >= 50} onClick={() => setSteps((items) => [...items, { name: "", approver_ids: [] }])}><Plus size={14} /> Add stage</button>
    </section>
    <label className="flex items-center gap-2 rounded-lg border border-line bg-muted p-3 text-[13px]"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Use this flow for new requests</label>
    <p className="text-xs text-fg-subtle">Assign this workflow in Employees → employee profile → Approval workflow. The same workflow can be assigned to several employees. Team and department changes do not affect routing.</p>
  </form></Sheet>;
}

function RequestPanel({ request, close }: { request: ApprovalRequest; close: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();
  const [comments, setComments] = useState("");
  const [level, setLevel] = useState(request.delegable_levels[0] ?? request.current_level);
  const [original, setOriginal] = useState(request.steps[level - 1]?.approver_ids[0] ?? "");
  const [replacement, setReplacement] = useState("");
  const [from, setFrom] = useState(() => localInput(new Date()));
  const [until, setUntil] = useState(() => localInput(new Date(Date.now() + 86400000)));
  const [reason, setReason] = useState("");
  const [flowWide, setFlowWide] = useState(false);
  const detail = useQuery({ queryKey: ["approval-request", request.id], queryFn: () => approvalsApi.detail(request.id) });
  const current = detail.data ?? request;
  const selectedLevel = current.delegable_levels.includes(level) ? level : (current.delegable_levels[0] ?? current.current_level);
  const stageApprovers = current.steps[selectedLevel - 1]?.approver_ids ?? [];
  const selectedOriginal = stageApprovers.includes(original) ? original : (stageApprovers[0] ?? "");
  const directory = useQuery({ queryKey: ["approval-directory", request.id], queryFn: () => approvalsApi.directory(request.id), enabled: !!current.delegable_levels.length });
  const delegations = useQuery({ queryKey: ["approval-delegations", request.id], queryFn: () => approvalsApi.delegations(request.id), enabled: request.approval_mode !== "POLICY" });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["approval-inbox"] }); qc.invalidateQueries({ queryKey: ["approval-request", request.id] }); qc.invalidateQueries({ queryKey: ["approval-delegations", request.id] }); qc.invalidateQueries({ queryKey: ["leave"] }); qc.invalidateQueries({ queryKey: ["corrections"] }); qc.invalidateQueries({ queryKey: ["overtime"] }); qc.invalidateQueries({ queryKey: ["recruitment-opening"] }); qc.invalidateQueries({ queryKey: ["recruitment-openings"] }); };
  const decide = useMutation({ mutationFn: (action: "APPROVE" | "REJECT") => approvalsApi.decide(request.id, action, comments), onSuccess: (updated) => { refresh(); toast.success(updated.status === "PENDING" ? "Stage approved" : `Request ${label(updated.status)}`); }, onError: (e) => toast.error("Couldn’t review request", errorMessage(e)) });
  const delegate = useMutation({ mutationFn: () => approvalsApi.delegate({ instance_id: request.id, level: selectedLevel, original_user_id: selectedOriginal, delegate_user_id: replacement, flow_wide: flowWide, valid_from: new Date(from).toISOString(), valid_until: new Date(until).toISOString(), reason }), onSuccess: () => { refresh(); setReason(""); toast.success("Delegation enabled"); }, onError: (e) => toast.error("Couldn’t enable delegation", errorMessage(e)) });
  const revoke = useMutation({ mutationFn: approvalsApi.revoke, onSuccess: refresh, onError: (e) => toast.error("Couldn’t revoke delegation", errorMessage(e)) });
  return <Sheet open onClose={close} title={TYPE_LABEL[current.request_type]} description={current.flow_name} className="max-w-xl" footer={current.can_act ? <>
    <button className="btn-secondary" disabled={decide.isPending || detail.isError} onClick={() => decide.mutate("REJECT")}>Reject request</button>
    <button className="btn-primary" disabled={decide.isPending || detail.isError} onClick={() => decide.mutate("APPROVE")}><Check size={15} /> {decide.isPending ? "Saving…" : "Approve stage"}</button>
  </> : <button className="btn-secondary" onClick={close}>Done</button>}><div className="space-y-6">
    <div data-autofocus tabIndex={-1} className="flex items-center gap-3 outline-none"><Avatar name={current.employee_name} size="lg" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-fg">{current.employee_name}</p><p className="text-xs text-fg-subtle">{current.employee_number}</p></div><StatusBadge status={current.status} /></div>
    {detail.isError && <Notice title="Couldn’t refresh request">Reload before taking action.</Notice>}
    {current.request_type === "JOB_REQUISITION" && <Link className="btn-secondary btn-sm w-full" to={`/recruitment/openings/${current.request_id}?tab=details`}>Read the full job description<ChevronRight size={13} /></Link>}
    <section><h3 className="eyebrow mb-3">Request details</h3><dl className="grid gap-x-4 gap-y-3 rounded-xl border border-line bg-muted/40 p-4 text-[13px] sm:grid-cols-2">{Object.entries(current.request).filter(([, v]) => v != null).map(([k, v]) => <div key={k} className={k.includes("reason") ? "sm:col-span-2" : ""}><dt className="text-xs text-fg-subtle">{DETAIL_LABEL[k] ?? label(k)}</dt><dd className="mt-1 break-words text-fg">{detailValue(k, v)}</dd></div>)}</dl></section>
    <section><div className="mb-3 flex items-center justify-between"><h3 className="eyebrow">Approval progress</h3><span className="text-xs text-fg-subtle">{current.steps.length} {current.steps.length === 1 ? "stage" : "stages"}</span></div>
    <ol className="space-y-2">{current.steps.map((step, i) => {
      const completed = current.status === "APPROVED" || i + 1 < current.current_level;
      const active = current.status === "PENDING" && i + 1 === current.current_level;
      return <li key={step.id ?? i} className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 ${active ? "border-brand-500/40 bg-brand-500/5" : "border-line"}`}>
        <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-medium ${completed ? "bg-success/10 text-success" : active ? "bg-brand-500/15 text-accent" : "bg-muted text-fg-subtle"}`}>{completed ? <Check size={14} /> : i + 1}</span>
        <span className="flex-1 text-[13px] font-medium text-fg">{step.name}</span><span className="text-xs text-fg-subtle">{completed ? "Approved" : active ? "Awaiting review" : current.status === "REJECTED" && i + 1 === current.current_level ? "Rejected" : current.status === "PENDING" ? "Upcoming" : "Not reached"}</span>
      </li>;
    })}</ol></section>
    {current.can_act && <label className="label block">Review comments <span className="font-normal text-fg-subtle">(optional)</span><textarea className="input mt-1" placeholder="Add a note for the employee…" rows={3} maxLength={1000} value={comments} onChange={(e) => setComments(e.target.value)} /></label>}
    {!!current.delegable_levels.length && <details className="rounded-xl border border-line"><summary className="cursor-pointer px-4 py-3 text-[13px] font-medium text-fg">Assign temporary cover</summary><form className="space-y-3 border-t border-line p-4" onSubmit={(e) => { e.preventDefault(); delegate.mutate(); }}>
      <p className="text-xs text-fg-subtle">Choose who can approve while the assigned person is absent.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="label">Stage<select className="input mt-1" value={selectedLevel} onChange={(e) => { const next = Number(e.target.value); setLevel(next); setOriginal(current.steps[next - 1].approver_ids[0]); }}>{current.delegable_levels.map((n) => <option key={n} value={n}>{n}. {current.steps[n - 1].name}</option>)}</select></label>
        <label className="label">Original approver<select className="input mt-1" value={selectedOriginal} onChange={(e) => setOriginal(e.target.value)}>{stageApprovers.map((id) => <option key={id} value={id}>{directory.data?.find((u) => u.id === id)?.name ?? id}</option>)}</select></label>
        <label className="label sm:col-span-2">Replacement<select required className="input mt-1" value={replacement} onChange={(e) => setReplacement(e.target.value)}><option value="">Choose person…</option>{directory.data?.filter((u) => u.employment_id !== current.employment_id && !current.steps.some((s) => s.approver_ids.includes(u.id))).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2"><label className="label">From (your local time)<input required className="input mt-1" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></label><label className="label">Until (your local time)<input required className="input mt-1" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} /></label></div>
      <label className="label">Reason<input required maxLength={1000} className="input mt-1" value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      {current.can_manage_flow && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={flowWide} onChange={(e) => setFlowWide(e.target.checked)} /> Apply to this stage across the flow during these dates</label>}
      <button className="btn-secondary" disabled={delegate.isPending || directory.isPending || directory.isError || !reason.trim() || !replacement}>Enable delegation</button>
    </form></details>}
    {!!delegations.data?.length && <div className="space-y-2"><h3 className="text-sm font-semibold">Delegations</h3>{delegations.data.map((d) => <div key={d.id} className="flex items-center justify-between gap-3 rounded-lg border border-line p-3 text-sm"><span>{d.reason} · until {new Date(d.valid_until).toLocaleString()} · {d.revoked_at ? "revoked" : "enabled during dates"}</span>{!d.revoked_at && (current.can_manage_flow || d.created_by === user?.id) && <button className="btn-ghost btn-sm" disabled={revoke.isPending} onClick={() => revoke.mutate(d.id)}>Revoke</button>}</div>)}</div>}
    {!!current.history?.length && <div className="space-y-2 border-t border-line pt-3"><h3 className="text-sm font-semibold">Approval history</h3>{current.history.map((h, i) => <p key={i} className="text-sm text-fg-subtle">{label(h.action)} · {String(h.details.step_name ?? h.details.reason ?? "")} · {h.actor_name} · {new Date(h.created_at).toLocaleString()}{h.details.delegation_id ? " · via delegation" : ""}{h.details.comments ? ` · ${String(h.details.comments)}` : ""}</p>)}</div>}
  </div></Sheet>;
}

function requestSummary(request: ApprovalRequest) {
  const data = request.request;
  const dateText = (v: unknown) => typeof v === "string" ? new Date(`${v}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "—";
  if (request.request_type === "LEAVE" || request.request_type === "LEAVE_CANCELLATION") return `${dateText(data.from_date)}${data.to_date !== data.from_date ? ` – ${dateText(data.to_date)}` : ""} · ${data.days_requested ?? "—"} ${Number(data.days_requested) === 1 ? "day" : "days"}`;
  if (request.request_type === "JOB_REQUISITION") return `${String(data.code ?? "")} · ${String(data.title ?? "")} · ${data.positions ?? 1} ${Number(data.positions) === 1 ? "position" : "positions"}`;
  if (request.request_type === "FIELD_OVERRIDE") {
    const apps = Array.isArray(data.apps) ? (data.apps as string[]).join(", ") : "an app";
    return `${label(String(data.type ?? data.action_type ?? "Change"))} from ${dateText(data.effective_date)} · managed in ${apps} · “${String(data.reason ?? "")}”`;
  }
  if (request.request_type === "OVERTIME") {
    const minutes = Number(data.ot_minutes ?? 0);
    return `${dateText(data.work_date)} · ${Math.floor(minutes / 60)}h ${minutes % 60}m overtime`;
  }
  return `${dateText(data.work_date)} · ${label(String(data.correction_type ?? "Correction"))}`;
}

export function ApprovalsPage({ view = "requests" }: { view?: "requests" | "flows" }) {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const canManage = !!user?.permissions.some((p) => p === "*" || p === "approvals.manage");
  const [tab, setTab] = useState<"all" | "mine">("all");
  const [editing, setEditing] = useState<ApprovalFlow | "new" | null>(null);
  const [selected, setSelected] = useState<ApprovalRequest | null>(null);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<RequestType | "">(() => TYPES.includes(params.get("type") as RequestType) ? params.get("type") as RequestType : "");
  const [enabledFilter, setEnabledFilter] = useState("");
  const [page, setPage] = useState(1);
  const isFlows = view === "flows";
  const inbox = useQuery({ queryKey: ["approval-inbox"], queryFn: approvalsApi.inbox, enabled: !isFlows });
  const flows = useQuery({ queryKey: ["approval-flows"], queryFn: approvalsApi.flows, enabled: isFlows && canManage });
  const query = search.trim().toLowerCase();
  const requests = (inbox.data ?? []).filter((r) => (!kind || r.request_type === kind) && (tab === "all" || r.can_act) && `${r.employee_name} ${r.employee_number} ${r.flow_name} ${r.steps[r.current_level - 1]?.name ?? ""}`.toLowerCase().includes(query));
  const filteredFlows = (flows.data ?? []).filter((f) => (!kind || f.request_type === kind) && (!enabledFilter || String(f.enabled) === enabledFilter) && `${f.name} ${f.steps.map((s) => s.name).join(" ")}`.toLowerCase().includes(query));
  const count = isFlows ? filteredFlows.length : requests.length;
  const totalPages = Math.max(1, Math.ceil(count / 10));
  const currentPage = Math.min(page, totalPages);
  const offset = (currentPage - 1) * 10;
  const loading = isFlows ? flows.isPending : inbox.isPending;
  const failed = isFlows ? flows.isError : inbox.isError;
  const mine = (inbox.data ?? []).filter((r) => r.can_act).length;
  if (isFlows && !canManage) return <Navigate to="/approvals" replace />;
  return <>
    <PageHeader title={isFlows ? "Approval flows" : "Approvals"}
      description={isFlows ? "Define reusable approval stages, then choose each employee’s workflow in their profile." : "Review employee requests and follow their approval progress."}
      actions={isFlows ? <><UsageHelpButton topic="approvals" /><button className="btn-primary" onClick={() => setEditing("new")}><Plus size={15} /> New flow</button></> : canManage ? <Link to="/approval-flows" className="btn-secondary"><Settings2 size={15} /> Manage flows</Link> : undefined} />
    {!isFlows && <div className="mb-6 grid gap-4 sm:grid-cols-3">
      <StatCard label="Pending requests" value={failed ? "—" : (inbox.data?.length ?? 0)} icon={ClipboardCheck} hint="Across your approval chains" loading={loading} />
      <StatCard label="Needs your review" value={failed ? "—" : mine} icon={Users} iconTone="orange" hint="Ready for your decision" loading={loading} />
      <StatCard label="Overtime requests" value={failed ? "—" : (inbox.data?.filter((r) => r.request_type === "OVERTIME").length ?? 0)} icon={Clock} iconTone="purple" hint="Awaiting approval" loading={loading} />
    </div>}
    {failed && <div className="mb-4"><Notice title={isFlows ? "Couldn’t load approval flows" : "Couldn’t load requests"} action={<button className="btn-secondary btn-sm" onClick={() => isFlows ? flows.refetch() : inbox.refetch()}>Retry</button>}>Try again to load the latest information.</Notice></div>}
    <div className="card overflow-hidden">
      {!isFlows && <div className="px-5 pt-1"><Tabs value={tab} onChange={(v) => { setTab(v); setPage(1); }} items={[
        { value: "all", label: "All pending", count: inbox.isPending || failed ? undefined : inbox.data?.length ?? 0 },
        { value: "mine", label: "Needs my review", count: inbox.isPending || failed ? undefined : mine },
      ]} /></div>}
      <div className="flex flex-wrap items-center gap-3 border-b border-line p-4 sm:px-5">
        <div className="relative min-w-0 flex-1 basis-56"><Search size={15} className="absolute left-3 top-2.5 text-fg-subtle" /><input className="input w-full pl-9" aria-label={isFlows ? "Search approval flows" : "Search approval requests"} placeholder={isFlows ? "Search workflows or stages…" : "Search employee, ID, or stage…"} value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} /></div>
        <select className="input w-full sm:w-48" aria-label="Filter by request type" value={kind} onChange={(e) => { setKind(e.target.value as RequestType | ""); setPage(1); }}><option value="">All request types</option>{TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select>
        {isFlows && <select className="input w-full sm:w-36" aria-label="Filter by flow status" value={enabledFilter} onChange={(e) => { setEnabledFilter(e.target.value); setPage(1); }}><option value="">All statuses</option><option value="true">Enabled</option><option value="false">Disabled</option></select>}
        {(search || kind || enabledFilter) && <button className="btn-ghost btn-sm" onClick={() => { setSearch(""); setKind(""); setEnabledFilter(""); setPage(1); }}>Clear filters</button>}
      </div>
      {loading ? <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div> : failed ? <EmptyState title="Information unavailable" description="Use Retry to load this page again." /> : !count ? <EmptyState icon={isFlows ? Settings2 : ClipboardCheck}
        title={search || kind || enabledFilter ? "No matching results" : isFlows ? "No approval flows yet" : tab === "mine" ? "All caught up" : "No pending requests"}
        description={search || kind || enabledFilter ? "Try another search or clear the filters." : isFlows ? "Create a workflow with its stages and approvers, then assign it to employees." : "Requests routed through configured flows appear here when they need approval."}
        action={isFlows && !search && !kind && !enabledFilter ? <button className="btn-primary" onClick={() => setEditing("new")}><Plus size={15} /> Create first flow</button> : undefined} /> : <>
        <div className="relative overflow-x-auto"><table className={`tbl ${isFlows ? "min-w-[880px]" : "min-w-[720px]"}`}><thead><tr>{isFlows ? <><th>Flow</th><th>Approval stages</th><th>Status</th><th className="relative"><span className="sr-only">Actions</span></th></> : <><th>Employee</th><th>Request</th><th>Current stage</th><th className="relative"><span className="sr-only">Actions</span></th></>}</tr></thead><tbody>
          {isFlows ? filteredFlows.slice(offset, offset + 10).map((flow) => <tr key={flow.id}>
            <td><p className="whitespace-nowrap font-medium text-fg">{flow.name}</p><p className="mt-1 text-xs text-fg-subtle">{TYPE_LABEL[flow.request_type]}</p></td>

            <td><div className="flex max-w-sm flex-wrap items-center gap-1.5">{flow.steps.map((s, i) => <span key={s.id ?? i} className="inline-flex items-center gap-1.5">{i > 0 && <ChevronRight size={12} className="text-fg-subtle" />}<span className="rounded-md border border-line bg-muted/40 px-2 py-1 text-xs text-fg-muted">{s.name}</span></span>)}</div></td>
            <td><StatusBadge status={flow.enabled ? "ACTIVE" : "INACTIVE"} label={flow.enabled ? "Enabled" : "Disabled"} /></td>
            <td><button className="btn-secondary btn-sm" disabled={flow.can_manage === false} onClick={() => setEditing(flow)} aria-label={`Edit ${flow.name}`}>Edit flow</button></td>
          </tr>) : requests.slice(offset, offset + 10).map((request) => <tr key={request.id}>
            <td><div className="flex items-center gap-3"><Avatar name={request.employee_name} /><div><p className="whitespace-nowrap font-medium text-fg">{request.employee_name}</p><p className="mt-1 text-xs text-fg-subtle">{request.employee_number}</p></div></div></td>
            <td><p className="font-medium text-fg">{TYPE_LABEL[request.request_type]}</p><p className="mt-1 whitespace-nowrap text-xs text-fg-subtle">{requestSummary(request)}</p></td>
            <td><p className="text-fg">{request.steps[request.current_level - 1]?.name}</p><p className="mt-1 text-xs text-fg-subtle">Stage {request.current_level} of {request.steps.length} · {request.flow_name}</p></td>
            <td><button className={request.can_act ? "btn-primary btn-sm" : "btn-secondary btn-sm"} onClick={() => setSelected(request)} aria-label={`${request.can_act ? "Review" : "View"} ${request.employee_name} ${TYPE_LABEL[request.request_type]}`}>{request.can_act ? "Review" : "View"}<ChevronRight size={13} /></button></td>
          </tr>)}
        </tbody></table></div>
        <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3"><p className="text-xs text-fg-subtle">Showing {offset + 1}–{Math.min(offset + 10, count)} of {count}</p><div className="flex items-center gap-2"><button className="btn-icon" aria-label="Previous page" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={15} /></button><span className="text-xs tabular-nums text-fg-muted">{currentPage} / {totalPages}</span><button className="btn-icon" aria-label="Next page" disabled={currentPage === totalPages} onClick={() => setPage(currentPage + 1)}><ChevronRight size={15} /></button></div></div>
      </>}
    </div>
    {isFlows && <p className="mt-4 text-xs text-fg-subtle">Assign saved workflows from each employee’s profile. Team and department changes do not change their workflow. Without a selected workflow, existing approval policies apply.</p>}
    {editing && <FlowEditor key={editing === "new" ? "new" : editing.id} initial={editing === "new" ? undefined : editing} close={() => setEditing(null)} />}
    {selected && <RequestPanel key={selected.id} request={selected} close={() => setSelected(null)} />}
  </>;
}

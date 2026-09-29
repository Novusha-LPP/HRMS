import { kycApi } from "../api/kyc";
import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { differenceInCalendarDays, format } from "date-fns";
import { Plus, Umbrella, CheckCheck, ChevronRight, CalendarRange, CloudOff, SlidersHorizontal } from "lucide-react";
import type { LeaveApplication, LeaveBalance, LeaveType } from "../api/leave";
import { leaveApi } from "../api/leave";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Tabs } from "../components/ui/Tabs";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Avatar } from "../components/ui/Avatar";
import { Sheet } from "../components/ui/Overlay";
import { ApprovalTimeline } from "../components/ui/Timeline";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { usePeopleDirectory } from "../lib/usePeopleDirectory";
import { LeaveLedgerView } from "../components/leave/LeaveLedgerView";

const PENDING = ["PENDING_L1", "PENDING_L2", "PENDING_L3"];
const CANCEL_PENDING = ["CANCEL_PENDING_L1", "CANCEL_PENDING_L2", "CANCEL_PENDING_L3"];
const needsDecision = (s: string) => PENDING.includes(s) || CANCEL_PENDING.includes(s);

function dateRange(a: string, b: string) {
  const from = new Date(a);
  const to = new Date(b);
  if (a === b) return format(from, "EEE, d MMM yyyy");
  const sameYear = from.getFullYear() === to.getFullYear();
  return `${format(from, sameYear ? "d MMM" : "d MMM yyyy")} – ${format(to, "d MMM yyyy")}`;
}

export function LeavePage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const role = user?.role ?? "EMPLOYEE";
  const isHR = role === "HR" || role === "SUPER_ADMIN";
  const isApprover = role === "MANAGER" || isHR;

  type LeaveTab = "all" | "approvals" | "ledger";
  const tabParam = params.get("tab");
  const tab: LeaveTab =
    tabParam === "approvals" && isApprover
      ? "approvals"
      : tabParam === "ledger"
      ? "ledger"
      : "all";
  const applyOpen = params.get("new") === "1";
  const [openId, setOpenId] = useState<string | null>(null);

  const updateParams = (mutate: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(params);
    mutate(next);
    setParams(next, { replace: true });
  };
  const setTab = (t: LeaveTab) =>
    updateParams((p) => {
      if (t !== "all") p.set("tab", t);
      else p.delete("tab");
    });
  const setApplyOpen = (open: boolean) => updateParams((p) => { if (open) p.set("new", "1"); else p.delete("new"); });
  const closeApply = () => setApplyOpen(false);

  const types = useQuery<LeaveType[]>({ queryKey: ["leave-types"], queryFn: () => leaveApi.listTypes() });
  const balances = useQuery<LeaveBalance[]>({
    queryKey: ["leave-balances", user?.employmentId],
    queryFn: () => leaveApi.getBalances(user!.employmentId!),
    enabled: !!user?.employmentId,
  });
  const apps = useQuery<LeaveApplication[]>({
    queryKey: ["leave-applications"],
    queryFn: () => leaveApi.listApplications(isHR ? undefined : (user!.employmentId ?? undefined)),
    // HR can review every request without being an employee themselves; everyone
    // else only ever sees their own, which needs their employment id.
    enabled: !!user && (isHR || !!user.employmentId),
  });
  const people = usePeopleDirectory(isApprover);

  // Moved below the hooks above (was an early return before them, which is a Rules-of-
  // Hooks violation — React needs the same hooks called in the same order every render).
  if (tabParam === "admin") return <Navigate to="/policy?tab=leave" replace />;
  if (!user) return null;
  const employmentId = user.employmentId;

  const all = apps.data ?? [];
  const pending = all.filter((a) => needsDecision(a.status));
  const list = tab === "approvals" ? pending : all;
  const selected = all.find((a) => a.id === openId) ?? null;

  return (
    <>
      <PageHeader
        title="Leave"
        description={isHR ? "Balances, requests and approvals across the organisation." : "Your balances and leave requests."}
        actions={
          <div className="flex items-center gap-2">
            {isHR && (
              <Link to="/policy?tab=leave" className="btn-secondary">
                <SlidersHorizontal size={14} /> Leave policies
              </Link>
            )}
            {employmentId && (
              <button className="btn-primary" onClick={() => setApplyOpen(true)}>
                <Plus size={15} /> Apply leave
              </button>
            )}
          </div>
        }
      />

      {!employmentId && (
        <div className="mb-4">
          <Notice tone="info" title="This account isn’t linked to an employee record">
            You can approve requests and configure leave for the company, but you can’t apply for leave yourself.
          </Notice>
        </div>
      )}

      {(apps.isError || balances.isError) && (
        <div className="mb-4">
          <Notice title="Couldn’t load leave data" action={<button className="btn-secondary btn-sm" onClick={() => { apps.refetch(); balances.refetch(); }}>Retry</button>}>
            The leave API isn’t responding.
          </Notice>
        </div>
      )}

      {employmentId && <section className="mb-6">
        <h2 className="eyebrow mb-3">My balance · {new Date().getFullYear()}</h2>
        {balances.isPending ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[132px] rounded-xl" />)}</div>
        ) : balances.isError ? (
          <div className="card"><EmptyState icon={CloudOff} title="Balances unavailable" description="They’ll appear once the leave service is reachable." className="py-10" /></div>
        ) : !balances.data?.length ? (
          <div className="card"><EmptyState icon={Umbrella} title="No leave balances yet" description="Balances appear once HR sets up leave types and allocates them for this year." className="py-10" /></div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {balances.data.map((b) => <BalanceCard key={b.id} bal={b} />)}
          </div>
        )}
      </section>}

      <div className="card overflow-hidden">
        <div className="px-5 pt-1">
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              {
                value: "all",
                label: isHR ? "All requests" : "My requests",
                count: apps.isPending ? undefined : all.length,
              },
              ...(isApprover
                ? [
                    {
                      value: "approvals" as const,
                      label: "Needs approval",
                      count: apps.isPending ? undefined : pending.length,
                    },
                  ]
                : []),
              { value: "ledger" as const, label: "Leave ledger & audit" },
            ]}
          />
        </div>

        {tab === "ledger" ? (
          <div className="p-5">
            <LeaveLedgerView
              currentEmploymentId={employmentId ?? null}
              isPrivileged={isApprover}
            />
          </div>
        ) : apps.isPending ? (
          <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : apps.isError ? (
          <EmptyState icon={CloudOff} title="Requests unavailable" description="They’ll appear once the leave service is reachable." />
        ) : list.length === 0 ? (
          tab === "approvals" ? (
            <EmptyState icon={CheckCheck} title="All caught up" description="There are no leave requests waiting for a decision." />
          ) : (
            <EmptyState
              icon={CalendarRange}
              title="No leave requests yet"
              description={employmentId ? "When you apply for leave, it’ll show up here with its approval status." : "Requests from people across the company will show up here."}
              action={employmentId ? <button className="btn-primary" onClick={() => setApplyOpen(true)}><Plus size={15} /> Apply leave</button> : undefined}
            />
          )
        ) : (
          <ul className="divide-y divide-line">
            {list.map((a) => (
              <li key={a.id}>
                <button onClick={() => setOpenId(a.id)} className="group flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors hover:bg-muted/50">
                  <span className="h-9 w-1 shrink-0 rounded-full" style={{ background: a.leave_type_color }} />
                  {isApprover && <Avatar name={people.get(a.employment_id) ?? a.employment_id} size="md" />}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-fg">
                      {isApprover ? <>{people.get(a.employment_id) ?? <span className="font-mono text-xs">{a.employment_id}</span>} <span className="font-normal text-fg-subtle">·</span> </> : null}
                      {a.leave_type_name}
                    </p>
                    <p className="truncate text-xs text-fg-subtle">
                      {dateRange(a.from_date, a.to_date)} · {a.days_requested} {a.days_requested === 1 ? "day" : "days"}
                      {a.half_day_option !== "NONE" && ` · ${a.half_day_option === "FIRST_HALF" ? "first half" : "second half"}`}
                    </p>
                  </div>
                  <StatusBadge status={a.status} />
                  <ChevronRight size={15} className="shrink-0 text-fg-subtle transition-transform group-hover:translate-x-0.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {employmentId && (
        <ApplyLeaveSheet
          open={applyOpen}
          onClose={closeApply}
          leaveTypes={(types.data ?? []).filter((t) => t.is_active)}
          typesError={types.isError}
          balances={balances.data ?? []}
          employmentId={employmentId}
        />
      )}
      <LeaveDetailSheet
        app={selected}
        onClose={() => setOpenId(null)}
        actorId={employmentId}
        isApprover={isApprover}
        requester={selected ? people.get(selected.employment_id) : undefined}
      />
    </>
  );
}

function BalanceCard({ bal }: { bal: LeaveBalance }) {
  const total = bal.allocated_days + bal.carry_forward_days;
  const usedPct = total > 0 ? Math.min(100, (bal.used_days / total) * 100) : 0;
  const pendingPct = total > 0 ? Math.min(100 - usedPct, (bal.pending_days / total) * 100) : 0;
  return (
    <div className="card p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2 text-[13px] font-medium text-fg">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: bal.color }} />
          <span className="truncate">{bal.leave_type_name}</span>
        </span>
        <span className="font-mono text-[11px] text-fg-subtle">{bal.leave_type_code}</span>
      </div>
      <p className="mt-3 text-[28px] font-semibold leading-none tracking-tight tabular-nums text-fg">
        {bal.available_days}
        <span className="ml-1.5 text-[13px] font-normal tracking-normal text-fg-subtle">of {total} days left</span>
      </p>
      <div className="mt-4 flex h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full" style={{ width: `${usedPct}%`, background: bal.color }} />
        <div className="h-full opacity-40" style={{ width: `${pendingPct}%`, background: bal.color }} />
      </div>
      <p className="mt-2 text-xs text-fg-subtle tabular-nums">
        {bal.used_days} used{bal.pending_days > 0 && ` · ${bal.pending_days} pending`}
        {bal.carry_forward_days > 0 && ` · ${bal.carry_forward_days} carried over`}
      </p>
    </div>
  );
}

function ApplyLeaveSheet({ open, onClose, leaveTypes, typesError, balances, employmentId }: {
  open: boolean;
  onClose: () => void;
  leaveTypes: LeaveType[];
  typesError: boolean;
  balances: LeaveBalance[];
  employmentId: string;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [typeId, setTypeId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [halfDay, setHalfDay] = useState("NONE");
  const [reason, setReason] = useState("");
  const [documentId, setDocumentId] = useState("");
  const documents = useQuery({
    queryKey: ["leave-supporting-documents", employmentId],
    queryFn: () => kycApi.getMyKyc(), enabled: open,
  });

  const ltId = typeId || leaveTypes[0]?.id || "";
  const type = leaveTypes.find((t) => t.id === ltId);
  const balance = balances.find((b) => b.leave_type_id === ltId);
  const end = to || from;
  const span = from && end ? differenceInCalendarDays(new Date(end), new Date(from)) + 1 : 0;
  const days = span === 1 && halfDay !== "NONE" ? 0.5 : span;

  const apply = useMutation({
    mutationFn: async () => {
      const app = await leaveApi.createApplication(employmentId, {
        leave_type_id: ltId, from_date: from, to_date: end, half_day_option: span > 1 ? "NONE" : halfDay, document_id: documentId || undefined, reason: reason.trim() || undefined,
      });
      return leaveApi.submit(app.id, employmentId);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-applications"] });
      qc.invalidateQueries({ queryKey: ["leave-balances"] });
      toast.success("Leave request submitted", `${type?.name ?? "Leave"} · ${dateRange(from, end)}`);
      setFrom(""); setTo(""); setHalfDay("NONE"); setReason("");
      onClose();
    },
    onError: (e) => toast.error("Couldn’t submit leave request", errorMessage(e)),
  });

  const valid = !!ltId && !!from && span > 0 && (!type?.requires_document || !!documentId);
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) apply.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Apply for leave"
      description="Your request goes to your approver once submitted."
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="apply-leave" disabled={!valid || apply.isPending}>
            {apply.isPending ? "Submitting…" : "Submit request"}
          </button>
        </>
      }
    >
      {typesError || leaveTypes.length === 0 ? (
        <Notice title={typesError ? "Couldn’t load leave types" : "No leave types configured"}>
          {typesError ? "The leave API isn’t responding." : "Ask HR to set up leave types before applying."}
        </Notice>
      ) : (
        <form id="apply-leave" onSubmit={submit} className="space-y-4">
          <div>
            <label className="label" htmlFor="lv-type">Leave type</label>
            <select id="lv-type" className="input" value={ltId} onChange={(e) => setTypeId(e.target.value)}>
              {leaveTypes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            {balance && (
              <p className="hint">
                <b className="font-medium text-fg">{balance.available_days} days</b> available
                {type && type.advance_notice_days > 0 && ` · ${type.advance_notice_days} days’ notice required`}
              </p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="lv-from">From</label>
              <input id="lv-from" type="date" className="input" value={from} onChange={(e) => { setFrom(e.target.value); if (!to || to < e.target.value) setTo(e.target.value); }} />
            </div>
            <div>
              <label className="label" htmlFor="lv-to">To</label>
              <input id="lv-to" type="date" className="input" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="lv-half">Duration</label>
            <select id="lv-half" className="input" value={halfDay} onChange={(e) => setHalfDay(e.target.value)} disabled={span > 1}>
              <option value="NONE">Full day{span > 1 ? "s" : ""}</option>
              <option value="FIRST_HALF">First half</option>
              <option value="SECOND_HALF">Second half</option>
            </select>
            {span > 1 && <p className="hint">Half days apply to single-day requests only.</p>}
          </div>
          {type?.requires_document && <div>
            <label className="label" htmlFor="lv-document">Supporting document</label>
            <select id="lv-document" className="input" value={documentId} onChange={e => setDocumentId(e.target.value)}>
              <option value="">Select an uploaded document</option>
              {documents.data?.documents.map(doc => <option key={doc.id} value={doc.id}>{doc.document_title}</option>)}
            </select>
            <p className="hint">Upload supporting documents from your profile's KYC tab.</p>
          </div>}
          <div>
            <label className="label" htmlFor="lv-reason">Reason <span className="font-normal text-fg-subtle">(optional)</span></label>
            <textarea id="lv-reason" rows={3} className="input" placeholder="A short note for your approver" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          {span > 0 && (
            <div className="flex items-center justify-between rounded-xl border border-line bg-panel px-4 py-3 text-[13px]">
              <span className="text-fg-muted">{dateRange(from, end)}</span>
              <span className="font-semibold tabular-nums text-fg">{days} {days === 1 ? "day" : "days"}</span>
            </div>
          )}
        </form>
      )}
    </Sheet>
  );
}

function LeaveDetailSheet({ app, onClose, actorId: actor, isApprover, requester }: {
  app: LeaveApplication | null;
  onClose: () => void;
  /** The signed-in user's employment; null for an admin-only account — it can approve, but has no requests of its own to cancel. */
  actorId: string | null;
  isApprover: boolean;
  requester?: string;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [comments, setComments] = useState("");

  const act = useMutation({
    mutationFn: ({ kind }: { kind: "approve" | "reject" | "cancel" | "cancelApprove" | "cancelReject" }) => {
      const id = app!.id;
      if (kind === "approve") return leaveApi.approve(id, comments || undefined);
      if (kind === "reject") return leaveApi.reject(id, comments || undefined);
      if (kind === "cancelApprove") return leaveApi.cancelApprove(id, comments || undefined);
      if (kind === "cancelReject") return leaveApi.cancelReject(id, comments || undefined);
      return leaveApi.cancel(id, actor as string, comments || undefined);
    },
    onSuccess: (_, { kind }) => {
      qc.invalidateQueries({ queryKey: ["leave-applications"] });
      qc.invalidateQueries({ queryKey: ["leave-balances"] });
      const msg = {
        approve: "Leave approved", reject: "Leave rejected", cancel: "Cancellation requested",
        cancelApprove: "Cancellation approved", cancelReject: "Leave kept — cancellation rejected",
      }[kind];
      toast.success(msg);
      setComments("");
      onClose();
    },
    onError: (e) => toast.error("Action failed", errorMessage(e)),
  });

  if (!app) return null;

  const isPending = PENDING.includes(app.status);
  const isCancelPending = CANCEL_PENDING.includes(app.status);
  const canDecide = isApprover && (isPending || isCancelPending);
  const canCancel = !!actor && app.employment_id === actor && ["DRAFT", ...PENDING, "APPROVED"].includes(app.status);
  const busy = act.isPending;

  const footer = canDecide ? (
    isPending ? (
      <>
        <button className="btn-danger-soft" onClick={() => act.mutate({ kind: "reject" })} disabled={busy}>Reject</button>
        <button className="btn-primary" onClick={() => act.mutate({ kind: "approve" })} disabled={busy}>Approve</button>
      </>
    ) : (
      <>
        <button className="btn-secondary" onClick={() => act.mutate({ kind: "cancelReject" })} disabled={busy}>Keep leave</button>
        <button className="btn-primary" onClick={() => act.mutate({ kind: "cancelApprove" })} disabled={busy}>Approve cancellation</button>
      </>
    )
  ) : canCancel ? (
    <button className="btn-danger-soft" onClick={() => act.mutate({ kind: "cancel" })} disabled={busy}>
      {isPending ? "Withdraw request" : "Cancel leave"}
    </button>
  ) : undefined;

  const level = Number(app.status.match(/L(\d)$/)?.[1] ?? app.current_level);

  return (
    <Sheet open onClose={onClose} title="Leave request" description={requester ? `Requested by ${requester}` : undefined} footer={footer}>
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl" style={{ background: `${app.leave_type_color}22`, color: app.leave_type_color }}>
              <Umbrella size={18} />
            </span>
            <div>
              <p className="text-[15px] font-semibold text-fg">{app.leave_type_name}</p>
              <p className="text-xs text-fg-subtle">{app.days_requested} {app.days_requested === 1 ? "day" : "days"}</p>
            </div>
          </div>
          <StatusBadge status={app.status} />
        </div>

        <dl className="divide-y divide-line rounded-xl border border-line text-[13px]">
          {[
            ["Dates", dateRange(app.from_date, app.to_date)],
            ["Duration", app.half_day_option === "NONE" ? "Full day" : app.half_day_option === "FIRST_HALF" ? "First half" : "Second half"],
            ["Approval", `${app.total_levels} level${app.total_levels > 1 ? "s" : ""}`],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 px-4 py-2.5">
              <dt className="text-fg-subtle">{k}</dt>
              <dd className="text-right font-medium text-fg">{v}</dd>
            </div>
          ))}
        </dl>

        {app.reason && (
          <div>
            <p className="eyebrow mb-2">Reason</p>
            <p className="rounded-xl bg-muted px-4 py-3 text-[13px] text-fg-muted">{app.reason}</p>
          </div>
        )}
        {app.cancel_reason && (
          <div>
            <p className="eyebrow mb-2">Cancellation reason</p>
            <p className="rounded-xl bg-muted px-4 py-3 text-[13px] text-fg-muted">{app.cancel_reason}</p>
          </div>
        )}

        <div>
          <p className="eyebrow mb-3">Activity</p>
          <ApprovalTimeline
            submittedAt={app.applied_at}
            steps={app.approval_history.map((h) => ({ id: h.id, action: h.action_type, level: h.level, comments: h.comments, at: h.actioned_at }))}
            pendingLevel={isPending || isCancelPending ? level : undefined}
            totalLevels={app.total_levels}
          />
        </div>

        {(canDecide || canCancel) && (
          <div>
            <label className="label" htmlFor="lv-comment">{canDecide ? "Comment" : "Reason"} <span className="font-normal text-fg-subtle">(optional)</span></label>
            <textarea id="lv-comment" rows={2} className="input" value={comments} onChange={(e) => setComments(e.target.value)} placeholder={canDecide ? "Visible to the requester" : "Why are you cancelling?"} />
          </div>
        )}
      </div>
    </Sheet>
  );
}

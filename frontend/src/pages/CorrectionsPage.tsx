import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { Plus, ChevronRight, FilePenLine, Clock, CloudOff } from "lucide-react";
import type { AttendanceCorrection } from "../api/corrections";
import { correctionsApi } from "../api/corrections";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Sheet } from "../components/ui/Overlay";
import { ApprovalTimeline } from "../components/ui/Timeline";
import { EmptyState, Notice, NoEmployeeRecord, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";

const CORRECTION_TYPES = [
  { value: "PUNCH_IN", label: "Correct check-in time" },
  { value: "PUNCH_OUT", label: "Correct check-out time" },
  { value: "MISSED_PUNCH", label: "Missed punch" },
  { value: "REGULARIZE", label: "Regularise (in & out)" },
  { value: "MARK_PRESENT", label: "Mark as present" },
  { value: "MARK_ABSENT", label: "Mark as absent" },
  { value: "LATE_REASON", label: "Late arrival — reason" },
  { value: "EARLY_DEPARTURE_REASON", label: "Early departure — reason" },
];
const typeLabel = (v: string) => CORRECTION_TYPES.find((t) => t.value === v)?.label ?? v;

const PENDING = ["PENDING_L1", "PENDING_L2", "PENDING_L3", "PENDING"];
const NEEDS_IN = new Set(["PUNCH_IN", "MISSED_PUNCH", "REGULARIZE", "MARK_PRESENT"]);
const NEEDS_OUT = new Set(["PUNCH_OUT", "MISSED_PUNCH", "REGULARIZE", "MARK_PRESENT"]);

function times(c: AttendanceCorrection) {
  const parts = [];
  if (c.requested_punch_in) parts.push(`In ${format(new Date(c.requested_punch_in), "hh:mm a")}`);
  if (c.requested_punch_out) parts.push(`Out ${format(new Date(c.requested_punch_out), "hh:mm a")}`);
  return parts.join(" · ");
}

/** The picker gives a wall-clock time in the user's own timezone; the API needs an unambiguous instant. */
const localToIso = (date: string, time: string) => new Date(`${date}T${time}:00`).toISOString();

export function CorrectionsPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const isApprover = !!user && (user.permissions.includes("*") || user.permissions.includes("corrections.approve"));

  const newOpen = params.get("new") === "1";
  const [openId, setOpenId] = useState<string | null>(null);

  const updateParams = (mutate: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(params);
    mutate(next);
    setParams(next, { replace: true });
  };
  const setNewOpen = (open: boolean) => updateParams((p) => { if (open) p.set("new", "1"); else p.delete("new"); });
  const closeNew = () => setNewOpen(false);

  const cors = useQuery<AttendanceCorrection[]>({
    queryKey: ["corrections", "mine", user?.employmentId],
    queryFn: () => correctionsApi.list(user!.employmentId!),
    enabled: !!user?.employmentId,
  });

  if (!user) return null;
  if (params.get("tab") === "approvals") return <Navigate to="/approvals?type=CORRECTION" replace />;
  const employmentId = user.employmentId;
  if (!employmentId) {
    return (
      <>
        <PageHeader
          title="Attendance corrections"
          description="Submit corrections to your attendance and track their status."
        />
        <NoEmployeeRecord feature="attendance history to correct" />
        {isApprover && <Link to="/approvals?type=CORRECTION" className="btn-secondary mt-4">Review correction requests<ChevronRight size={15} /></Link>}
      </>
    );
  }

  const all = cors.data ?? [];
  const list = all;
  const selected = all.find((c) => c.id === openId) ?? null;

  return (
    <>
      <PageHeader
        title="Attendance corrections"
        description="Submit corrections to your attendance and track their status."
        actions={employmentId ? <button className="btn-primary" onClick={() => setNewOpen(true)}><Plus size={15} /> Request correction</button> : undefined}
      />

      {cors.isError && (
        <div className="mb-4">
          <Notice title="Couldn’t load corrections" action={<button className="btn-secondary btn-sm" onClick={() => cors.refetch()}>Retry</button>}>
            The corrections API isn’t responding.
          </Notice>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="card-header border-b border-line pb-4">
          <h3 className="card-title">My requests</h3>
          <span className="text-xs text-fg-subtle">{all.length} total</span>
        </div>

        {cors.isPending ? (
          <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : cors.isError ? (
          <EmptyState icon={CloudOff} title="Requests unavailable" description="They’ll appear once the corrections service is reachable." />
        ) : list.length === 0 ? (
          <EmptyState
            icon={FilePenLine}
            title="No correction requests"
            description="Forgot to check in or out? Request a correction and your approver will review it."
            action={<button className="btn-primary" onClick={() => setNewOpen(true)}><Plus size={15} /> Request correction</button>}
          />
        ) : (
          <ul className="divide-y divide-line">
            {list.map((c) => {
              return (
                <li key={c.id}>
                  <button onClick={() => setOpenId(c.id)} className="group flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors hover:bg-muted/50">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-muted text-fg-subtle"><Clock size={15} /></span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium text-fg">
                        {typeLabel(c.correction_type)}
                      </p>
                      <p className="truncate text-xs text-fg-subtle">
                        {format(new Date(c.work_date), "EEE, d MMM yyyy")}{times(c) && ` · ${times(c)}`}
                      </p>
                    </div>
                    <StatusBadge status={c.status} />
                    <ChevronRight size={15} className="shrink-0 text-fg-subtle transition-transform group-hover:translate-x-0.5" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {employmentId && <NewCorrectionSheet open={newOpen} onClose={closeNew} employmentId={employmentId} />}
      <CorrectionDetailSheet
        cor={selected}
        onClose={() => setOpenId(null)}
        actorId={employmentId}
      />
    </>
  );
}

function NewCorrectionSheet({ open, onClose, employmentId }: { open: boolean; onClose: () => void; employmentId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [type, setType] = useState("MISSED_PUNCH");
  const [workDate, setWorkDate] = useState(format(new Date(), "yyyy-MM-dd"));
  const [punchIn, setPunchIn] = useState("");
  const [punchOut, setPunchOut] = useState("");
  const [reason, setReason] = useState("");

  const mut = useMutation({
    mutationFn: () => correctionsApi.create(employmentId, {
      work_date: workDate,
      correction_type: type,
      requested_punch_in: NEEDS_IN.has(type) && punchIn ? localToIso(workDate, punchIn) : undefined,
      requested_punch_out: NEEDS_OUT.has(type) && punchOut ? localToIso(workDate, punchOut) : undefined,
      reason: reason.trim(),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["corrections"] });
      qc.invalidateQueries({ queryKey: ["approval-inbox"] });
      toast.success("Correction requested", `${typeLabel(type)} · ${format(new Date(workDate), "d MMM")}`);
      setReason(""); setPunchIn(""); setPunchOut("");
      onClose();
    },
    onError: (e) => toast.error("Couldn’t submit correction", errorMessage(e)),
  });

  const valid = !!reason.trim() && !!workDate;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) mut.mutate(); };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Request a correction"
      description="Tell your approver what needs fixing and why."
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="new-correction" disabled={!valid || mut.isPending}>
            {mut.isPending ? "Submitting…" : "Submit request"}
          </button>
        </>
      }
    >
      <form id="new-correction" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="cr-type">What needs correcting?</label>
          <select id="cr-type" className="input" value={type} onChange={(e) => setType(e.target.value)}>
            {CORRECTION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="cr-date">Date</label>
          <input id="cr-date" type="date" className="input" value={workDate} max={format(new Date(), "yyyy-MM-dd")} onChange={(e) => setWorkDate(e.target.value)} />
        </div>
        {(NEEDS_IN.has(type) || NEEDS_OUT.has(type)) && (
          <div className="grid grid-cols-2 gap-3">
            {NEEDS_IN.has(type) && (
              <div>
                <label className="label" htmlFor="cr-in">Check-in time</label>
                <input id="cr-in" type="time" className="input" value={punchIn} onChange={(e) => setPunchIn(e.target.value)} />
              </div>
            )}
            {NEEDS_OUT.has(type) && (
              <div>
                <label className="label" htmlFor="cr-out">Check-out time</label>
                <input id="cr-out" type="time" className="input" value={punchOut} onChange={(e) => setPunchOut(e.target.value)} />
              </div>
            )}
          </div>
        )}
        <div>
          <label className="label" htmlFor="cr-reason">Reason</label>
          <textarea id="cr-reason" rows={3} className="input" placeholder="e.g. Biometric device was offline at the gate" value={reason} onChange={(e) => setReason(e.target.value)} />
          <p className="hint">Required — approvers see this first.</p>
        </div>
      </form>
    </Sheet>
  );
}

function CorrectionDetailSheet({ cor, onClose, actorId }: {
  cor: AttendanceCorrection | null;
  onClose: () => void;
  actorId: string | null;
}) {
  const qc = useQueryClient();
  const toast = useToast();

  const act = useMutation({
    mutationFn: () => correctionsApi.cancel(cor!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["corrections"] });
      qc.invalidateQueries({ queryKey: ["approval-inbox"] });
      toast.success("Request withdrawn");
      onClose();
    },
    onError: (e) => toast.error("Action failed", errorMessage(e)),
  });

  if (!cor) return null;

  const isPending = PENDING.includes(cor.status);
  const canWithdraw = (isPending || cor.status === "DRAFT") && !!actorId && cor.employment_id === actorId;
  const level = Number(cor.status.match(/L(\d)$/)?.[1] ?? cor.current_level);

  const footer = canWithdraw ? (
    <button className="btn-danger-soft" onClick={() => act.mutate()} disabled={act.isPending}>Withdraw request</button>
  ) : undefined;

  return (
    <Sheet open onClose={onClose} title="Correction request" footer={footer}>
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[15px] font-semibold text-fg">{typeLabel(cor.correction_type)}</p>
            <p className="text-xs text-fg-subtle">{format(new Date(cor.work_date), "EEEE, d MMMM yyyy")}</p>
          </div>
          <StatusBadge status={cor.status} />
        </div>

        {(cor.requested_punch_in || cor.requested_punch_out) && (
          <div className="grid grid-cols-2 divide-x divide-line rounded-xl border border-line">
            <div className="px-4 py-3">
              <p className="text-xs text-fg-subtle">Requested check-in</p>
              <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-fg">{cor.requested_punch_in ? format(new Date(cor.requested_punch_in), "hh:mm a") : "—"}</p>
            </div>
            <div className="px-4 py-3">
              <p className="text-xs text-fg-subtle">Requested check-out</p>
              <p className="mt-0.5 text-[15px] font-semibold tabular-nums text-fg">{cor.requested_punch_out ? format(new Date(cor.requested_punch_out), "hh:mm a") : "—"}</p>
            </div>
          </div>
        )}

        <div>
          <p className="eyebrow mb-2">Reason</p>
          <p className="rounded-xl bg-muted px-4 py-3 text-[13px] text-fg-muted">{cor.reason}</p>
        </div>

        <div>
          <p className="eyebrow mb-3">Activity</p>
          <ApprovalTimeline
            submittedAt={cor.submitted_at}
            steps={cor.approval_history.map((h) => ({ id: h.id, action: h.action, level: h.level, comments: h.comments, at: h.actioned_at }))}
            pendingLevel={isPending ? level : undefined}
            totalLevels={cor.total_levels}
          />
        </div>

      </div>
    </Sheet>
  );
}

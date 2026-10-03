import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Check, CheckCheck, Clock, FileClock, Inbox, Umbrella, X } from "../icons/ThemeIcons";
import { leaveApi } from "../../api/leave";
import { correctionsApi } from "../../api/corrections";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { Avatar } from "../ui/Avatar";
import { useToast } from "../ui/Toast";

/** A pending leave request or attendance correction, merged and sorted by the backend so
 *  the dashboard can answer "who applied for what, and is it waiting on me" at a glance. */
export interface PendingRequestItem {
  kind: "LEAVE" | "CORRECTION" | "PERSONNEL_ACTION";
  id: string;
  employment_id: string;
  name: string;
  department?: string;
  company?: string;
  detail: string;
  is_cancellation?: boolean;
  submitted_at: string;
  link: string;
}

/* ── Needs your decision: the merged, actionable leave + correction queue ── */
export function PendingApprovalsQueue({ items, isLoading, queryKeyToRefresh, emptyHint }: {
  items: PendingRequestItem[];
  isLoading: boolean;
  /** Query keys to invalidate after a decision, so counts/lists elsewhere update too. */
  queryKeyToRefresh: unknown[][];
  emptyHint: string;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);

  const decide = useMutation({
    mutationFn: async ({ item, approve }: { item: PendingRequestItem; approve: boolean }) => {
      setBusyId(item.id);
      if (item.kind === "LEAVE") {
        return item.is_cancellation
          ? approve ? leaveApi.cancelApprove(item.id) : leaveApi.cancelReject(item.id)
          : approve ? leaveApi.approve(item.id) : leaveApi.reject(item.id);
      }
      if (item.kind === "CORRECTION") {
        return approve ? correctionsApi.approve(item.id) : correctionsApi.reject(item.id);
      }
      // Personnel actions are reviewed from the Employees page, not decided here.
      throw new Error("Open this from the Employees page to decide it.");
    },
    onSuccess: (_, { item, approve }) => {
      for (const key of queryKeyToRefresh) qc.invalidateQueries({ queryKey: key });
      toast.success(
        approve ? "Approved" : "Rejected",
        `${item.name} · ${item.detail}`,
      );
    },
    onError: (e) => toast.error("Couldn’t record that decision", e instanceof Error ? e.message : undefined),
    onSettled: () => setBusyId(null),
  });

  const iconFor = (kind: PendingRequestItem["kind"]) =>
    kind === "LEAVE" ? Umbrella : kind === "CORRECTION" ? FileClock : Clock;
  const toneFor = (kind: PendingRequestItem["kind"]) =>
    kind === "LEAVE" ? "bg-info/10 text-info" : kind === "CORRECTION" ? "bg-warning/10 text-warning" : "bg-fg/[0.06] text-fg-subtle";

  return (
    <div className="card flex flex-col">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-danger/10 text-danger">
            <Inbox size={16} />
          </div>
          <div>
            <h3 className="card-title">Needs your decision</h3>
            <p className="card-desc">Leave requests and attendance corrections waiting on you</p>
          </div>
        </div>
        {items.length > 0 && <span className="badge badge-neutral">{items.length}</span>}
      </div>

      {isLoading ? (
        <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full rounded-lg" />)}</div>
      ) : items.length === 0 ? (
        <div className="flex-1 flex items-center justify-center p-5">
          <EmptyState icon={CheckCheck} title="All caught up" description={emptyHint} className="py-6" />
        </div>
      ) : (
        <ul className="divide-y divide-line border-t border-line flex-1">
          {items.map((it) => {
            const Icon = iconFor(it.kind);
            const busy = busyId === it.id && decide.isPending;
            const canDecideHere = it.kind !== "PERSONNEL_ACTION";
            return (
              <li key={`${it.kind}-${it.id}`} className="flex items-center gap-3 px-5 py-3 text-[13px] hover:bg-muted/40 transition-colors">
                <Avatar name={it.name} size="sm" />
                <span className={`hidden sm:flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${toneFor(it.kind)}`}>
                  <Icon size={12} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-fg">
                    {it.name}
                    {it.is_cancellation && <span className="ml-1.5 badge badge-warning align-middle text-[10px]">Cancellation</span>}
                  </p>
                  <p className="truncate text-xs text-fg-subtle">
                    {it.detail}
                    {(it.department || it.company) && ` · ${[it.department, it.company].filter(Boolean).join(" · ")}`}
                  </p>
                </div>
                <span className="hidden shrink-0 text-[11px] text-fg-subtle md:inline">
                  {formatDistanceToNow(new Date(it.submitted_at), { addSuffix: true })}
                </span>
                {canDecideHere ? (
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      title="Reject" disabled={busy}
                      onClick={() => decide.mutate({ item: it, approve: false })}
                      className="grid h-7 w-7 place-items-center rounded-md text-fg-subtle transition-colors hover:bg-danger/10 hover:text-danger disabled:opacity-50"
                    >
                      <X size={14} />
                    </button>
                    <button
                      title={it.is_cancellation ? "Approve cancellation" : "Approve"} disabled={busy}
                      onClick={() => decide.mutate({ item: it, approve: true })}
                      className="grid h-7 w-7 place-items-center rounded-md text-fg-subtle transition-colors hover:bg-success/10 hover:text-success disabled:opacity-50"
                    >
                      <Check size={14} />
                    </button>
                  </div>
                ) : (
                  <Link to={it.link} className="link shrink-0 text-xs">Review</Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {items.length > 0 && (
        <div className="flex items-center gap-4 border-t border-line px-5 py-2.5">
          {items.some((i) => i.kind === "LEAVE") && <Link to="/leave?tab=approvals" className="link text-xs">Leave queue →</Link>}
          {items.some((i) => i.kind === "CORRECTION") && <Link to="/approvals?type=CORRECTION" className="link text-xs">Corrections queue →</Link>}
        </div>
      )}
    </div>
  );
}

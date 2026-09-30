import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import {
  Users, UserCheck, CalendarCheck, CalendarX2, Umbrella, Inbox,
  Cake, Award, CheckCheck,
  Copy, Check, BarChart3, FilePenLine, Timer, Sparkles, UserPlus,
  X, FileClock, Clock,
} from "lucide-react";
import { dashboardApi } from "../api/dashboard";
import { leaveApi } from "../api/leave";
import type { LeaveApplicationSummary, LeaveBalance } from "../api/leave";
import { correctionsApi } from "../api/corrections";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { Donut, Legend, CHART } from "../components/ui/Charts";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { PunchClock } from "../components/attendance/PunchClock";
import { OnboardingChecklist } from "../components/onboarding/OnboardingChecklist";
import { Avatar } from "../components/ui/Avatar";
import { useToast } from "../components/ui/Toast";

type Dict = Record<string, unknown>;
const num = (v: unknown, fallback = 0) => (typeof v === "number" ? v : fallback);

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function ApiNotice({ onRetry }: { onRetry: () => void }) {
  return (
    <Notice
      title="Live data is unavailable"
      action={<button onClick={onRetry} className="btn-secondary btn-sm shrink-0">Retry</button>}
    >
      The API isn’t responding, so the figures below aren’t current. Start the backend and run migrations (see RUNBOOK.md).
    </Notice>
  );
}

interface BirthdayItem {
  name: string;
  employee_number: string;
  department: string;
  company: string;
  date: string;
  days_until: number;
}

interface AnnivItem {
  name: string;
  employee_number: string;
  department: string;
  company: string;
  date: string;
  days_until: number;
  years: number;
}


/** A pending leave request or attendance correction, merged and sorted by the backend so
 *  the dashboard can answer "who applied for what, and is it waiting on me" at a glance. */
interface PendingRequestItem {
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

interface RecentJoinerItem {
  name: string;
  employee_number: string;
  hire_date?: string;
  company: string;
  department: string;
}

/* ── Needs your decision: the merged, actionable leave + correction queue ── */
function PendingApprovalsQueue({ items, isLoading, queryKeyToRefresh, emptyHint }: {
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
          {items.some((i) => i.kind === "CORRECTION") && <Link to="/corrections?tab=approvals" className="link text-xs">Corrections queue →</Link>}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────── HR / Admin ─────────────────────────── */
function HRDashboard() {
  const toast = useToast();
  const [copiedName, setCopiedName] = useState<string | null>(null);

  const { data, isPending: isLoading, isError, refetch } = useQuery({
    queryKey: ["dash-hr"],
    queryFn: () => dashboardApi.hr(),
  });

  const { data: leaveSummary } = useQuery<LeaveApplicationSummary>({
    queryKey: ["leave-applications", "summary"],
    queryFn: () => leaveApi.applicationSummary(),
  });

  const hc = (data?.headcount as Dict) ?? {};
  const today = (data?.today as Dict) ?? {};
  const month = (data?.month as Dict) ?? {};
  const actions = (data?.actions as Dict) ?? {};
  const birthdays = (data?.upcoming_birthdays as BirthdayItem[]) ?? [];
  const anniversaries = (data?.upcoming_anniversaries as AnnivItem[]) ?? [];
  const recentJoiners = (data?.recent_joiners as RecentJoinerItem[]) ?? [];
  const pendingRequests = (data?.pending_requests as PendingRequestItem[]) ?? [];

  const total = num(hc.total);
  const present = num(today.present);
  const absent = num(today.absent);
  const onLeave = num(today.on_leave);
  const late = num(today.late);
  const newHires = num(month.new_hires);
  const pending = num(actions.pending_approvals);
  const pendingLeave = num(actions.pending_leave);
  const pendingCorrections = num(actions.pending_corrections);
  const pendingPersonnel = num(actions.pending_personnel_actions);
  const presentPct = total > 0 ? Math.round((present / total) * 100) : 0;

  const byStatus = leaveSummary?.by_status ?? {};
  const countOf = (match: (status: string) => boolean) =>
    Object.entries(byStatus).reduce((n, [status, count]) => (match(status) ? n + count : n), 0);
  const leaveLive = Object.keys(byStatus).length > 0;
  const leaveStatus = {
    pending: countOf((s) => s.includes("PENDING")),
    approved: countOf((s) => s === "APPROVED"),
    rejected: countOf((s) => s === "REJECTED"),
  };
  const leaveTypes = (leaveSummary?.approved_days_by_type ?? []).map((t) => ({
    label: t.name, value: t.days, color: t.color,
  }));
  const leaveTotal = leaveTypes.reduce((s, t) => s + t.value, 0) || 1;

  const handleCopyWish = (bday: BirthdayItem) => {
    const text = `Happy Birthday ${bday.name}! Wishing you a wonderful year filled with joy, health, and success from everyone at ${bday.company}! 🎂🎉`;
    navigator.clipboard.writeText(text);
    setCopiedName(bday.name);
    toast.success("Greeting copied to clipboard", `Personalized birthday message for ${bday.name} is ready to paste.`);
    setTimeout(() => setCopiedName(null), 3000);
  };

  return (
    <div className="space-y-6">
      {isError && <ApiNotice onRetry={() => refetch()} />}

      {/* ─── Top Row: Plain KPI StatCards ──────────────────────────────────── */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Headcount"
          icon={Users}
          loading={isLoading}
          value={total}
          delta={newHires}
          hint="joined this month"
        />
        <StatCard
          label="Present today"
          icon={UserCheck}
          loading={isLoading}
          value={present}
          hint={`${presentPct}% of workforce`}
        />
        <StatCard
          label="On leave today"
          icon={Umbrella}
          loading={isLoading}
          value={onLeave}
          hint={`${absent} unplanned absences`}
        />
        <StatCard
          label="Pending approvals"
          icon={Inbox}
          loading={isLoading}
          value={pending}
          hint={pending === 0 ? "all caught up" : [
            pendingLeave && `${pendingLeave} leave`,
            pendingCorrections && `${pendingCorrections} correction${pendingCorrections === 1 ? "" : "s"}`,
            pendingPersonnel && `${pendingPersonnel} personnel`,
          ].filter(Boolean).join(" · ")}
        />
      </div>

      {/* ─── Row 2: Attendance Operations Pulse & Leave Breakdown ───────────── */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Attendance Pulse */}
        <div className="card">
          <div className="card-header">
            <div>
              <h3 className="card-title">Today</h3>
              <p className="card-desc">{format(new Date(), "EEEE, d MMM")}</p>
            </div>
            <Link to="/daily-analysis" className="link text-xs">Daily analysis</Link>
          </div>
          <div className="flex flex-col items-center gap-6 px-5 pb-5 sm:flex-row">
            {isLoading ? (
              <Skeleton className="h-[152px] w-[152px] rounded-full" />
            ) : (
              <Donut
                segments={[
                  { label: "On time", value: Math.max(present - late, 0), color: CHART.present },
                  { label: "Late", value: late, color: CHART.late },
                  { label: "Absent", value: absent, color: CHART.absent },
                  { label: "On leave", value: onLeave, color: CHART.leave },
                ]}
              >
                <span className="text-2xl font-bold tabular-nums text-fg">{presentPct}%</span>
                <span className="text-[11px] text-fg-subtle">present</span>
              </Donut>
            )}
            <div className="w-full flex-1">
              <Legend
                items={[
                  { label: "On time", color: CHART.present, value: isLoading ? "–" : Math.max(present - late, 0) },
                  { label: "Late arrivals", color: CHART.late, value: isLoading ? "–" : late },
                  { label: "Absent (unplanned)", color: CHART.absent, value: isLoading ? "–" : absent },
                  { label: "On approved leave", color: CHART.leave, value: isLoading ? "–" : onLeave },
                ]}
              />
            </div>
          </div>
        </div>

        {/* Needs your decision — who applied for leave/corrections, actionable right here */}
        <PendingApprovalsQueue
          items={pendingRequests}
          isLoading={isLoading}
          queryKeyToRefresh={[["dash-hr"], ["leave-applications"], ["corrections"]]}
          emptyHint="No leave requests or attendance corrections are waiting on a decision."
        />
      </div>

      {/* ─── Leave activity: days taken by category, across everyone in scope ─── */}
      {leaveLive && (
        <div className="card">
          <div className="card-header">
            <div>
              <h3 className="card-title">Leave activity</h3>
              <p className="card-desc">Days taken by category, and how requests have been resolved</p>
            </div>
            <Link to="/leave" className="link text-xs">Open leave</Link>
          </div>
          <div className="px-5 pb-5">
            <div className="grid grid-cols-3 divide-x divide-line rounded-xl border border-line bg-surface-raised/40">
              {[
                { label: "Pending", value: leaveStatus.pending, cls: "text-amber-500" },
                { label: "Approved", value: leaveStatus.approved, cls: "text-emerald-500" },
                { label: "Rejected", value: leaveStatus.rejected, cls: "text-rose-500" },
              ].map((s) => (
                <div key={s.label} className="px-3 py-3 text-center">
                  <p className={`text-xl font-bold tabular-nums ${s.cls}`}>{s.value}</p>
                  <p className="text-[11px] text-fg-subtle">{s.label}</p>
                </div>
              ))}
            </div>
            <p className="eyebrow mb-2.5 mt-5">Days by leave category</p>
            <div className="flex h-2 overflow-hidden rounded-full bg-muted">
              {leaveTypes.map((t) => (
                <div
                  key={t.label}
                  style={{ width: `${(t.value / leaveTotal) * 100}%`, background: t.color }}
                  className="h-full first:rounded-l-full last:rounded-r-full"
                />
              ))}
            </div>
            <div className="mt-4">
              <Legend items={leaveTypes.map((t) => ({ label: t.label, color: t.color, value: `${t.value}d` }))} />
            </div>
          </div>
        </div>
      )}

      {/* ─── Row 3: People & Culture Hub (Birthdays, Anniversaries, New Hires) ─ */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Column 1: Birthdays (DOB) */}
        <div className="card flex flex-col">
          <div className="card-header">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-pink-500/10 text-pink-500">
                <Cake size={16} />
              </div>
              <div>
                <h3 className="card-title">Upcoming Birthdays</h3>
                <p className="card-desc">Celebrating in the next 45 days</p>
              </div>
            </div>
            <Link to="/employees" className="link text-xs">All</Link>
          </div>

          {isLoading ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full rounded-lg" />)}
            </div>
          ) : birthdays.length === 0 ? (
            <div className="flex-1 flex items-center justify-center p-5">
              <EmptyState icon={Cake} title="No upcoming birthdays" description="No birthdays recorded in the next 45 days." className="py-6" />
            </div>
          ) : (
            <ul className="divide-y divide-line border-t border-line flex-1">
              {birthdays.map((b, i) => (
                <li key={i} className="flex items-center justify-between gap-3 px-5 py-3 text-[13px] hover:bg-muted/40 transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <Avatar name={b.name} size="sm" />
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-fg">{b.name}</p>
                      <p className="truncate text-xs text-fg-subtle">{b.department} • {b.company}</p>
                    </div>
                  </div>
                  <div className="shrink-0 flex items-center gap-2">
                    {b.days_until === 0 ? (
                      <span className="badge badge-success font-semibold animate-pulse">Today! 🎉</span>
                    ) : b.days_until === 1 ? (
                      <span className="badge badge-warning">Tomorrow</span>
                    ) : (
                      <span className="badge badge-neutral text-xs">
                        {format(new Date(b.date), "d MMM")} • {b.days_until}d
                      </span>
                    )}
                    <button
                      onClick={() => handleCopyWish(b)}
                      title="Copy birthday wish"
                      className="p-1 rounded-md text-fg-subtle hover:text-pink-600 hover:bg-pink-500/10 transition-colors"
                    >
                      {copiedName === b.name ? <Check size={14} className="text-success" /> : <Copy size={13} />}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Column 2: Work Anniversaries (DOJ) */}
        <div className="card flex flex-col">
          <div className="card-header">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10 text-amber-500">
                <Sparkles size={16} />
              </div>
              <div>
                <h3 className="card-title">Work Anniversaries</h3>
                <p className="card-desc">Milestone tenures this month</p>
              </div>
            </div>
            <Link to="/employees" className="link text-xs">All</Link>
          </div>

          {isLoading ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full rounded-lg" />)}
            </div>
          ) : anniversaries.length === 0 ? (
            <div className="flex-1 flex items-center justify-center p-5">
              <EmptyState icon={Award} title="No milestones" description="No work anniversaries in the upcoming 45 days." className="py-6" />
            </div>
          ) : (
            <ul className="divide-y divide-line border-t border-line flex-1">
              {anniversaries.map((a, i) => (
                <li key={i} className="flex items-center justify-between gap-3 px-5 py-3 text-[13px] hover:bg-muted/40 transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <Avatar name={a.name} size="sm" />
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-fg">{a.name}</p>
                      <p className="truncate text-xs text-fg-subtle">{a.department} • {a.company}</p>
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <span className="badge badge-accent font-semibold">
                      {a.years} {a.years === 1 ? "year" : "years"}
                    </span>
                    <p className="text-[11px] text-fg-subtle mt-0.5">{format(new Date(a.date), "d MMM")}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Column 3: Recent Joiners */}
        <div className="card flex flex-col">
          <div className="card-header">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500/10 text-purple-600 dark:text-purple-400">
                <UserPlus size={16} />
              </div>
              <div>
                <h3 className="card-title">Welcome New Joiners</h3>
                <p className="card-desc">Recent additions to the team</p>
              </div>
            </div>
            <Link to="/employees" className="link text-xs">Directory</Link>
          </div>

          {isLoading ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full rounded-lg" />)}
            </div>
          ) : recentJoiners.length === 0 ? (
            <div className="flex-1 flex items-center justify-center p-5">
              <EmptyState icon={UserPlus} title="No recent joiners" description="New hires will be welcomed here." className="py-6" />
            </div>
          ) : (
            <ul className="divide-y divide-line border-t border-line flex-1">
              {recentJoiners.map((j, i) => (
                <li key={i} className="flex items-center justify-between gap-3 px-5 py-3 text-[13px] hover:bg-muted/40 transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <Avatar name={j.name} size="sm" />
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-fg">{j.name}</p>
                      <p className="truncate text-xs text-fg-subtle">{j.department} • {j.company}</p>
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <span className="badge badge-neutral text-xs">
                      {j.hire_date ? format(new Date(j.hire_date), "d MMM yyyy") : "Recent"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── Manager ─────────────────────────── */
function ManagerDashboard({ employmentId }: { employmentId: string }) {
  const { data, isPending: isLoading, isError, refetch } = useQuery({
    queryKey: ["dash-mgr", employmentId],
    queryFn: () => dashboardApi.manager(employmentId),
  });
  const today = (data?.today as Dict) ?? {};
  const approvals = (data?.pending_approvals as PendingRequestItem[]) ?? [];

  return (
    <div className="space-y-6">
      {isError && <ApiNotice onRetry={() => refetch()} />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Team size" icon={Users} loading={isLoading} value={num(data?.team_size)} />
        <StatCard label="Present today" icon={UserCheck} loading={isLoading} value={num(today.present)} />
        <StatCard label="Absent today" icon={CalendarX2} loading={isLoading} value={num(today.absent)} />
        <StatCard label="On leave" icon={Umbrella} loading={isLoading} value={num(today.on_leave)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <PendingApprovalsQueue
            items={approvals}
            isLoading={isLoading}
            queryKeyToRefresh={[["dash-mgr", employmentId], ["leave-applications"], ["corrections"]]}
            emptyHint="New requests from your team will appear here."
          />
        </div>
        <PunchClock employmentId={employmentId} />
      </div>
    </div>
  );
}

/* ─────────────────────────── Employee ─────────────────────────── */
function EmployeeDashboard({ employmentId }: { employmentId: string }) {
  const { data, isPending: isLoading, isError, refetch } = useQuery({
    queryKey: ["dash-emp", employmentId],
    queryFn: () => dashboardApi.employee(employmentId),
  });
  const { data: balances, isPending: balLoading } = useQuery<LeaveBalance[]>({
    queryKey: ["leave-balances", employmentId],
    queryFn: () => leaveApi.getBalances(employmentId),
  });
  const m = (data?.month_summary as Dict) ?? {};

  return (
    <div className="space-y-6">
      {isError && <ApiNotice onRetry={() => refetch()} />}
      <div className="grid gap-4 lg:grid-cols-3">
        <PunchClock employmentId={employmentId} />
        <div className="space-y-4 lg:col-span-2">
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Days present" icon={CalendarCheck} loading={isLoading} value={num(m.present)} hint={String(m.month ?? "This month")} />
            <StatCard label="Late arrivals" icon={Timer} loading={isLoading} value={num(m.late)} hint="this month" />
            <StatCard label="Days absent" icon={CalendarX2} loading={isLoading} value={num(m.absent)} hint="this month" />
          </div>
          <div className="card">
            <div className="card-header">
              <h3 className="card-title">Leave balance</h3>
              <Link to="/leave" className="link text-xs">View leave</Link>
            </div>
            {balLoading ? (
              <div className="space-y-3 px-5 pb-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-8" />)}</div>
            ) : !balances?.length ? (
              <EmptyState icon={Umbrella} title="No leave balances yet" description="Balances appear once HR sets up leave types for your year." className="py-10" />
            ) : (
              <ul className="space-y-3 px-5 pb-5">
                {balances.map((b) => {
                  const total = b.allocated_days + b.carry_forward_days;
                  return (
                    <li key={b.id}>
                      <div className="mb-1.5 flex items-center justify-between text-[13px]">
                        <span className="flex items-center gap-2 text-fg"><span className="h-2 w-2 rounded-full" style={{ background: b.color }} />{b.leave_type_name}</span>
                        <span className="tabular-nums text-fg-muted"><b className="font-semibold text-fg">{b.available_days}</b> / {total} days</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full" style={{ width: `${total ? (b.available_days / total) * 100 : 0}%`, background: b.color }} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </div>
      <OnboardingChecklist employmentId={employmentId} hideWhenEmpty />
    </div>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  if (!user) return null;
  // Admin-only accounts have no person record, so their "name" is just their email.
  const first = user.name.includes("@") ? "" : user.name.split(" ")[0];
  const isHR = user.role === "HR" || user.role === "SUPER_ADMIN";

  const actions = isHR ? (
    <>
      <Link to="/employees" className="btn-secondary"><Users size={15} /> Employees</Link>
      <Link to="/reports" className="btn-secondary"><BarChart3 size={15} /> Reports</Link>
      <Link to="/leave?tab=approvals" className="btn-primary"><CheckCheck size={15} /> Review approvals</Link>
    </>
  ) : (
    <>
      <Link to="/corrections?new=1" className="btn-secondary"><FilePenLine size={15} /> Request correction</Link>
      <Link to="/leave?new=1" className="btn-primary"><Umbrella size={15} /> Apply leave</Link>
    </>
  );

  return (
    <>
      <PageHeader
        title={first ? `${greeting()}, ${first}` : greeting()}
        description={isHR ? `Here’s what’s happening across ${user.tenantName} today.` : "Here’s your day at a glance."}
        actions={actions}
      />
      {isHR && <HRDashboard />}
      {user.role === "MANAGER" && user.employmentId && <ManagerDashboard employmentId={user.employmentId} />}
      {user.role === "EMPLOYEE" && user.employmentId && <EmployeeDashboard employmentId={user.employmentId} />}
      {!isHR && !user.employmentId && <HRDashboard />}
    </>
  );
}

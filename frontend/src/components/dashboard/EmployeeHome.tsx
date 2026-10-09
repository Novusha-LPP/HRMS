/**
 * The employee's own home: their day, their week, balances, requests and holidays.
 * Every card reads the person's own records through the self-service endpoints; managers
 * get the same cards under their team summary.
 */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { addDays, format, isToday, parseISO, startOfWeek } from "date-fns";
import {
  CalendarCheck, CalendarX2, ChevronRight, FileClock, Gift, ShieldAlert, Timer, Umbrella, Clock,
} from "../icons/ThemeIcons";
import type { EmployeeDashboard, UpcomingHoliday } from "../../api/dashboard";
import { DECISION_STATUSES, leaveApi } from "../../api/leave";
import type { LeaveApplication, LeaveBalance } from "../../api/leave";
import { correctionsApi } from "../../api/corrections";
import { kycApi } from "../../api/kyc";
import { timeApi } from "../../api/time";
import type { RegisterDay } from "../../api/time";
import { StatCard } from "../ui/StatCard";
import { StatusBadge, humanize } from "../ui/StatusBadge";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { fmtMins } from "../attendance/registerModel";

const isoDay = (d: Date) => format(d, "yyyy-MM-dd");

function hours(minutes: number | undefined) {
  if (!minutes) return "0h";
  const h = Math.floor(minutes / 60);
  return h >= 10 ? `${h}h` : fmtMins(minutes);
}

function dateRange(from: string, to: string) {
  const a = parseISO(from);
  const b = parseISO(to);
  if (from === to) return format(a, "EEE, d MMM");
  return a.getMonth() === b.getMonth() ? `${format(a, "d")}–${format(b, "d MMM")}` : `${format(a, "d MMM")} – ${format(b, "d MMM")}`;
}

/* ─────────────────────────── Month at a glance ─────────────────────────── */

export function MonthStats({ data, loading }: { data?: EmployeeDashboard; loading: boolean }) {
  const m = data?.month_summary;
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <StatCard label="Days present" icon={CalendarCheck} iconTone="green" loading={loading} value={m?.present ?? 0} hint={m?.month ?? "This month"} />
      <StatCard label="Late arrivals" icon={Timer} iconTone="orange" loading={loading} value={m?.late ?? 0} hint="this month" />
      <StatCard label="Days absent" icon={CalendarX2} iconTone="red" loading={loading} value={m?.absent ?? 0} hint="this month" />
      <StatCard label="Hours worked" icon={Clock} iconTone="purple" loading={loading} value={hours(m?.worked_minutes)} hint="this month" />
    </div>
  );
}

/* ─────────────────────────── This week ─────────────────────────── */

const DAY_TONE: Record<string, string> = {
  PRESENT: "bg-success", OFF_DAY_WORKED: "bg-success",
  LATE: "bg-warning", HALF_DAY: "bg-warning",
  ABSENT: "bg-danger", MISSED_PUNCH: "bg-danger",
  ON_LEAVE: "bg-info", HOLIDAY: "bg-plum",
};

function dayCaption(d: RegisterDay) {
  if (d.first_punch_in) return d.effective_minutes ? fmtMins(d.effective_minutes) : "In";
  if (d.status === "ON_LEAVE") return d.leave_type ?? "Leave";
  if (d.status === "HOLIDAY") return d.holiday_name ?? "Holiday";
  if (d.status === "WEEKEND") return "Week off";
  if (d.status === "UPCOMING") return "—";
  return humanize(d.status);
}

export function WeekStrip({ employmentId }: { employmentId: string }) {
  const monday = startOfWeek(new Date(), { weekStartsOn: 1 });
  const from = isoDay(monday);
  const to = isoDay(addDays(monday, 6));
  // Shares the "attendance-register" prefix, so a punch on the time clock refreshes it.
  const { data, isPending, isError } = useQuery({
    queryKey: ["attendance-register", employmentId, "week", from],
    queryFn: () => timeApi.register(employmentId, from, to),
  });
  const byDate = new Map((data?.days ?? []).map((d) => [d.work_date, d]));
  const worked = (data?.days ?? []).reduce((sum, d) => sum + (d.effective_minutes || 0), 0);

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3 className="card-title">This week</h3>
          <p className="card-desc">{format(monday, "d MMM")} – {format(addDays(monday, 6), "d MMM")} · {fmtMins(worked, "0h")} worked</p>
        </div>
        <Link to="/attendance" className="link text-xs">My attendance</Link>
      </div>
      <div className="px-5 pb-5">
        {isError ? (
          <p className="text-[13px] text-fg-subtle">Your week couldn’t be loaded right now.</p>
        ) : (
          <ol className="grid grid-cols-7 gap-1.5 sm:gap-2">
            {Array.from({ length: 7 }, (_, i) => {
              const date = addDays(monday, i);
              const day = byDate.get(isoDay(date));
              const today = isToday(date);
              return (
                <li
                  key={i}
                  className={`flex min-w-0 flex-col items-center rounded-lg border px-1 py-2 text-center ${today ? "border-brand-500/50 bg-brand-500/[0.06]" : "border-line bg-panel"}`}
                  title={day ? `${format(date, "EEEE d MMM")}: ${humanize(day.status)}` : format(date, "EEEE d MMM")}
                >
                  <span className={`text-[11px] font-medium ${today ? "text-accent" : "text-fg-subtle"}`}>{format(date, "EEE")}</span>
                  <span className="text-[15px] font-semibold tabular-nums text-fg">{format(date, "d")}</span>
                  {isPending ? (
                    <Skeleton className="mt-1.5 h-1.5 w-6 rounded-full" />
                  ) : (
                    <span className={`mt-1.5 h-1.5 w-6 rounded-full ${day ? DAY_TONE[day.status] ?? "bg-line" : "bg-line"}`} />
                  )}
                  <span className="mt-1 hidden w-full truncate text-[10px] tabular-nums text-fg-subtle sm:block">{day ? dayCaption(day) : "—"}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────── Leave balance ─────────────────────────── */

export function LeaveBalanceCard({ employmentId }: { employmentId: string }) {
  const { data: balances, isPending } = useQuery<LeaveBalance[]>({
    queryKey: ["leave-balances", employmentId],
    queryFn: () => leaveApi.getBalances(employmentId),
  });
  return (
    <div className="card">
      <div className="card-header">
        <h3 className="card-title">Leave balance</h3>
        <Link to="/leave?new=1" className="link text-xs">Apply leave</Link>
      </div>
      {isPending ? (
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
                  <span className="flex min-w-0 items-center gap-2 text-fg"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: b.color }} /><span className="truncate">{b.leave_type_name}</span></span>
                  <span className="shrink-0 tabular-nums text-fg-muted"><b className="font-semibold text-fg">{b.available_days}</b> / {total} days</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full" style={{ width: `${total ? Math.min(100, (b.available_days / total) * 100) : 0}%`, background: b.color }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ─────────────────────────── My requests ─────────────────────────── */

interface RequestRow { key: string; title: string; detail: string; status: string; to: string; color?: string; icon: typeof Umbrella }

export function MyRequestsCard({ employmentId }: { employmentId: string }) {
  const today = isoDay(new Date());
  const pendingLeave = useQuery({
    queryKey: ["leave-applications", "mine-pending", employmentId],
    queryFn: () => leaveApi.listApplications({ employmentId, statuses: DECISION_STATUSES, limit: 20 }),
  });
  const approvedLeave = useQuery({
    queryKey: ["leave-applications", "mine-approved", employmentId],
    queryFn: () => leaveApi.listApplications({ employmentId, statuses: ["APPROVED"], limit: 50 }),
  });
  // Same key as the Corrections page, so both share one cached list.
  const corrections = useQuery({
    queryKey: ["corrections", "mine", employmentId],
    queryFn: () => correctionsApi.list(employmentId),
  });

  const leaveRow = (a: LeaveApplication): RequestRow => ({
    key: a.id,
    title: a.leave_type_name,
    detail: `${dateRange(a.from_date, a.to_date)} · ${a.days_requested} ${a.days_requested === 1 ? "day" : "days"}`,
    status: a.status,
    to: "/leave",
    color: a.leave_type_color,
    icon: Umbrella,
  });
  const waiting: RequestRow[] = [
    ...(pendingLeave.data ?? []).map(leaveRow),
    ...(corrections.data ?? [])
      .filter((c) => c.status.startsWith("PENDING"))
      .map((c) => ({
        key: c.id,
        title: `Correction · ${humanize(c.correction_type)}`,
        detail: format(parseISO(c.work_date), "EEE, d MMM"),
        status: c.status,
        to: "/corrections",
        icon: FileClock,
      })),
  ];
  const upcoming = (approvedLeave.data ?? [])
    .filter((a) => a.to_date >= today)
    .sort((a, b) => a.from_date.localeCompare(b.from_date))
    .slice(0, 3)
    .map(leaveRow);
  const loading = pendingLeave.isPending || corrections.isPending || approvedLeave.isPending;

  const list = (rows: RequestRow[]) => (
    <ul className="divide-y divide-line">
      {rows.map((r) => (
        <li key={r.key}>
          <Link to={r.to} className="flex items-center gap-3 px-5 py-2.5 transition-colors hover:bg-muted/50">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-line bg-panel" style={r.color ? { color: r.color } : undefined}>
              <r.icon size={14} className={r.color ? "" : "text-fg-subtle"} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium text-fg">{r.title}</span>
              <span className="block truncate text-xs text-fg-subtle">{r.detail}</span>
            </span>
            <StatusBadge status={r.status} />
          </Link>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="card flex flex-col">
      <div className="card-header">
        <div>
          <h3 className="card-title">My requests</h3>
          <p className="card-desc">{waiting.length ? `${waiting.length} waiting for approval` : "Nothing waiting for approval"}</p>
        </div>
        <Link to="/corrections?new=1" className="link text-xs">Request correction</Link>
      </div>
      {loading ? (
        <div className="space-y-3 px-5 pb-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>
      ) : !waiting.length && !upcoming.length ? (
        <EmptyState icon={FileClock} title="No open requests" description="Leave you apply for and attendance corrections you request show up here until they’re decided." className="py-10" />
      ) : (
        <div className="pb-2">
          {!!waiting.length && <>
            <p className="eyebrow px-5 pb-1">Awaiting approval</p>
            {list(waiting.slice(0, 4))}
          </>}
          {!!upcoming.length && <>
            <p className={`eyebrow px-5 pb-1 ${waiting.length ? "pt-3" : ""}`}>Upcoming leave</p>
            {list(upcoming)}
          </>}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────── Holidays ─────────────────────────── */

function whenLabel(daysAway: number) {
  if (daysAway === 0) return "Today";
  if (daysAway === 1) return "Tomorrow";
  if (daysAway < 7) return `In ${daysAway} days`;
  if (daysAway < 60) return `In ${Math.round(daysAway / 7)} wk`;
  return `In ${Math.round(daysAway / 30)} mo`;
}

export function UpcomingHolidaysCard({ holidays, loading }: { holidays?: UpcomingHoliday[]; loading: boolean }) {
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3 className="card-title">Upcoming holidays</h3>
          <p className="card-desc">From your holiday calendar</p>
        </div>
      </div>
      {loading ? (
        <div className="space-y-3 px-5 pb-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
      ) : !holidays?.length ? (
        <EmptyState icon={Gift} title="No upcoming holidays" description="Holidays appear here once HR assigns a holiday calendar that covers you." className="py-10" />
      ) : (
        <ul className="space-y-1 px-3 pb-4">
          {holidays.map((h) => {
            const d = parseISO(h.date);
            return (
              <li key={`${h.date}-${h.name}`} className="flex items-center gap-3 rounded-lg px-2 py-1.5">
                <span className="flex w-11 shrink-0 flex-col items-center rounded-lg border border-line bg-panel py-1 leading-none">
                  <span className="text-[10px] font-medium uppercase text-plum">{format(d, "MMM")}</span>
                  <span className="mt-0.5 text-[15px] font-semibold tabular-nums text-fg">{format(d, "d")}</span>
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium text-fg">{h.name}</span>
                  <span className="block text-xs text-fg-subtle">{format(d, "EEEE")}{h.is_optional && " · Optional"}</span>
                </span>
                <span className={`shrink-0 text-xs tabular-nums ${h.days_away <= 1 ? "font-medium text-accent" : "text-fg-subtle"}`}>{whenLabel(h.days_away)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ─────────────────────────── To-dos ─────────────────────────── */

const KYC_TODO: Partial<Record<string, string>> = {
  NOT_SUBMITTED: "Add your identity, bank and address details so HR can verify them.",
  DRAFT: "You’ve started your KYC — finish and submit it for HR to verify.",
  REJECTED: "HR sent your KYC back. Review the comments and resubmit.",
  ACTION_REQUIRED: "HR needs a change to your KYC. Review the comments and resubmit.",
};

export function KycTodo() {
  const { data } = useQuery({ queryKey: ["my-kyc"], queryFn: () => kycApi.getMyKyc(), retry: false });
  const todo = data && KYC_TODO[data.status];
  if (!todo) return null;
  return (
    <Notice
      tone="info"
      title="Complete your KYC"
      action={<Link to="/profile?tab=kyc" className="btn-secondary btn-sm shrink-0">Open KYC <ChevronRight size={13} /></Link>}
    >
      <span className="inline-flex items-center gap-1.5"><ShieldAlert size={13} className="shrink-0" />{todo}</span>
    </Notice>
  );
}

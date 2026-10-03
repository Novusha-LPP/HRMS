/**
 * The HR dashboard's widgets. ./registry.ts maps the ids in
 * backend/src/hrms/modules/dashboard/widgets.py (the catalog, permissions and allowed sizes
 * live there) to these components. Each renders from the /v1/dashboard/hr payload fetched
 * for the sections its layout needs.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Armchair, Award, Briefcase, Building2, Cake, CalendarClock, ChartPie, Check, ClipboardCheck, Copy,
  DoorOpen, FilePenLine, Gift, Hourglass, IdCard, Inbox, ListChecks, LogOut, MapPin, Plane,
  RefreshCw, ShieldCheck, Sparkles, Timer, TriangleAlert, UserCheck, UserMinus, UserPlus, Users,
  Umbrella, Zap, ActionUserPlus, ActionCorrection, ActionReports,
} from "../icons/ThemeIcons";
import type { LucideIcon } from "lucide-react";
import type { WidgetSize } from "../../api/dashboard";
import { leaveApi } from "../../api/leave";
import type { LeaveApplicationSummary } from "../../api/leave";
import { StatCard } from "../ui/StatCard";
import { BarList, DepartmentChart, DepartmentProgress, Donut, Legend } from "../ui/Charts";
import { CHART } from "../ui/chartPalette";
import { useTheme } from "../../context/ThemeContext";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { Avatar } from "../ui/Avatar";
import { useToast } from "../ui/Toast";
import { PendingApprovalsQueue } from "./PendingApprovalsQueue";
import type { PendingRequestItem } from "./PendingApprovalsQueue";

type Dict = Record<string, unknown>;
const num = (v: unknown, fallback = 0) => (typeof v === "number" ? v : fallback);
const dict = (v: unknown) => (v && typeof v === "object" ? (v as Dict) : {});

export interface WidgetProps {
  data: Dict | undefined;
  loading: boolean;
  size: WidgetSize;
}

/* ── Shared card chrome ─────────────────────────────────────────────────── */

function Card({ icon: Icon, tone, title, description, link, children }: {
  icon: LucideIcon;
  tone: string;
  title: string;
  description: string;
  link?: { to: string; label: string };
  children: ReactNode;
}) {
  return (
    <div className="card flex h-full flex-col">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${tone}`}>
            <Icon size={16} />
          </div>
          <div>
            <h3 className="card-title">{title}</h3>
            <p className="card-desc">{description}</p>
          </div>
        </div>
        {link && <Link to={link.to} className="link text-xs">{link.label}</Link>}
      </div>
      {children}
    </div>
  );
}

function ListSkeleton() {
  return <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full rounded-lg" />)}</div>;
}

function Empty({ icon, title, description }: { icon: LucideIcon; title: string; description: string }) {
  return (
    <div className="flex flex-1 items-center justify-center p-5">
      <EmptyState icon={icon} title={title} description={description} className="py-6" />
    </div>
  );
}

interface PersonRow { name: string; department: string; company: string }

function PeopleList<T extends PersonRow>({ rows, right }: { rows: T[]; right: (row: T) => ReactNode }) {
  return (
    <ul className="flex-1 divide-y divide-line border-t border-line">
      {rows.map((row, i) => (
        <li key={i} className="flex items-center justify-between gap-3 px-5 py-3 text-[13px] transition-colors hover:bg-muted/40">
          <div className="flex min-w-0 items-center gap-3">
            <Avatar name={row.name} size="sm" />
            <div className="min-w-0">
              <p className="truncate font-semibold text-fg">{row.name}</p>
              <p className="truncate text-xs text-fg-subtle">{row.department} • {row.company}</p>
            </div>
          </div>
          <div className="shrink-0">{right(row)}</div>
        </li>
      ))}
    </ul>
  );
}

/* ── KPI cards ──────────────────────────────────────────────────────────── */

export function KpiHeadcount({ data, loading }: WidgetProps) {
  return (
    <StatCard label="Headcount" icon={Users} loading={loading} value={num(dict(data?.headcount).total)}
      delta={num(dict(data?.month).new_hires)} hint="joined this month" />
  );
}

export function KpiPresentToday({ data, loading }: WidgetProps) {
  const total = num(dict(data?.headcount).total);
  const present = num(dict(data?.today).present);
  const pct = total > 0 ? Math.round((present / total) * 100) : 0;
  return <StatCard iconTone="green" label="Present today" icon={UserCheck} loading={loading} value={present} hint={`${pct}% of workforce`} />;
}

export function KpiOnLeaveToday({ data, loading }: WidgetProps) {
  const today = dict(data?.today);
  return (
    <StatCard iconTone="orange" label="On leave today" icon={Umbrella} loading={loading} value={num(today.on_leave)}
      hint={`${num(today.absent)} unplanned absences`} />
  );
}

export function KpiPendingApprovals({ data, loading }: WidgetProps) {
  const a = dict(data?.actions);
  const pending = num(a.pending_approvals);
  const leave = num(a.pending_leave);
  const corrections = num(a.pending_corrections);
  const personnel = num(a.pending_personnel_actions);
  return (
    <StatCard iconTone="purple" label="Pending approvals" icon={Inbox} loading={loading} value={pending}
      hint={pending === 0 ? "all caught up" : [
        leave && `${leave} leave`,
        corrections && `${corrections} correction${corrections === 1 ? "" : "s"}`,
        personnel && `${personnel} personnel`,
      ].filter(Boolean).join(" · ")} />
  );
}

export function KpiOpenOnboarding({ data, loading }: WidgetProps) {
  const open = num(dict(data?.actions).open_onboarding);
  return <StatCard iconTone="green" label="Onboarding in progress" icon={ClipboardCheck} loading={loading} value={open}
    hint={open === 0 ? "nobody mid-onboarding" : "new hires still onboarding"} />;
}

export function KpiPendingKyc({ data, loading }: WidgetProps) {
  const pending = num(dict(data?.actions).pending_kyc);
  return <StatCard iconTone="teal" label="KYC to verify" icon={ShieldCheck} loading={loading} value={pending}
    hint={pending === 0 ? "nothing waiting" : "submitted, awaiting verification"} />;
}

/* ── Attendance, approvals, leave ───────────────────────────────────────── */

export function AttendanceToday({ data, loading }: WidgetProps) {
  const { colorTheme } = useTheme();
  const midnight = colorTheme === "midnight-blue";
  const today = dict(data?.today);
  const total = num(dict(data?.headcount).total);
  const present = num(today.present);
  const late = num(today.late);
  const absent = num(today.absent);
  const onLeave = num(today.on_leave);
  const pct = total > 0 ? Math.round((present / total) * (midnight ? 1000 : 100)) / (midnight ? 10 : 1) : 0;
  const onTime = Math.max(present - late, 0);
  const referenceValue = (value: number) => loading ? "–" : `${value} (${total ? Math.round(value / total * 1000) / 10 : 0}%)`;
  const legend = midnight ? [
    { label: "Present", color: CHART.present, value: referenceValue(present) },
    { label: "Absent", color: CHART.absent, value: referenceValue(absent) },
    { label: "Late", color: CHART.late, value: referenceValue(late) },
    { label: "On Leave", color: CHART.leave, value: referenceValue(onLeave) },
  ] : [
    { label: "On time", color: CHART.present, value: loading ? "–" : onTime },
    { label: "Late arrivals", color: CHART.late, value: loading ? "–" : late },
    { label: "Absent (unplanned)", color: CHART.absent, value: loading ? "–" : absent },
    { label: "On approved leave", color: CHART.leave, value: loading ? "–" : onLeave },
  ];
  return (
    <div className="card flex h-full flex-col">
      <div className="card-header">
        <div>
          <h3 className="card-title">Today</h3>
          <p className="card-desc">{format(new Date(), "EEEE, d MMM")}</p>
        </div>
        <Link to="/daily-analysis" className="link text-xs">Daily analysis</Link>
      </div>
      <div className="flex flex-col items-center gap-6 px-5 pb-5 sm:flex-row">
        {loading ? (
          <Skeleton className="h-[152px] w-[152px] rounded-full" />
        ) : (
          <Donut segments={[
            { label: "On time", value: onTime, color: CHART.present },
            { label: "Late", value: late, color: CHART.late },
            { label: "Absent", value: absent, color: CHART.absent },
            { label: "On leave", value: onLeave, color: CHART.leave },
          ]}>
            <span className="text-2xl font-bold tabular-nums text-fg">{pct}%</span>
            <span className="text-[11px] text-fg-subtle">{midnight ? "Present %" : "present"}</span>
          </Donut>
        )}
        <div className="w-full flex-1">
          <Legend items={legend} />
        </div>
      </div>
    </div>
  );
}

export function ApprovalsQueue({ data, loading }: WidgetProps) {
  return (
    <div className="h-full [&>.card]:h-full">
      <PendingApprovalsQueue
        items={(data?.pending_requests as PendingRequestItem[]) ?? []}
        isLoading={loading}
        queryKeyToRefresh={[["dash-hr"], ["leave-applications"], ["corrections"]]}
        emptyHint="No leave requests or attendance corrections are waiting on a decision."
      />
    </div>
  );
}

export function LeaveActivity() {
  const { data, isPending } = useQuery<LeaveApplicationSummary>({
    queryKey: ["leave-applications", "summary"],
    queryFn: () => leaveApi.applicationSummary(),
  });
  const byStatus = data?.by_status ?? {};
  const countOf = (match: (s: string) => boolean) =>
    Object.entries(byStatus).reduce((n, [s, c]) => (match(s) ? n + c : n), 0);
  const types = (data?.approved_days_by_type ?? []).map((t) => ({ label: t.name, value: t.days, color: t.color }));
  const total = types.reduce((s, t) => s + t.value, 0) || 1;
  return (
    <Card icon={Umbrella} tone="bg-info/10 text-info" title="Leave activity"
      description="Days taken by category, and how requests have been resolved"
      link={{ to: "/leave", label: "Open leave" }}>
      <div className="px-5 pb-5">
        {isPending ? <Skeleton className="h-24 w-full rounded-xl" /> : (
          <>
            <div className="grid grid-cols-3 divide-x divide-line rounded-xl border border-line bg-surface-raised/40">
              {[
                { label: "Pending", value: countOf((s) => s.includes("PENDING")), cls: "text-amber-500" },
                { label: "Approved", value: countOf((s) => s === "APPROVED"), cls: "text-emerald-500" },
                { label: "Rejected", value: countOf((s) => s === "REJECTED"), cls: "text-rose-500" },
              ].map((s) => (
                <div key={s.label} className="px-3 py-3 text-center">
                  <p className={`text-xl font-bold tabular-nums ${s.cls}`}>{s.value}</p>
                  <p className="text-[11px] text-fg-subtle">{s.label}</p>
                </div>
              ))}
            </div>
            {types.length > 0 && (
              <>
                <p className="eyebrow mb-2.5 mt-5">Days by leave category</p>
                <div className="flex h-2 overflow-hidden rounded-full bg-muted">
                  {types.map((t) => (
                    <div key={t.label} style={{ width: `${(t.value / total) * 100}%`, background: t.color }}
                      className="h-full first:rounded-l-full last:rounded-r-full" />
                  ))}
                </div>
                <div className="mt-4">
                  <Legend items={types.map((t) => ({ label: t.label, color: t.color, value: `${t.value}d` }))} />
                </div>
              </>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

/* ── People ─────────────────────────────────────────────────────────────── */

interface BirthdayItem extends PersonRow { date: string; days_until: number }
interface AnnivItem extends PersonRow { date: string; years: number }
interface JoinerItem extends PersonRow { hire_date?: string }

export function UpcomingBirthdays({ data, loading }: WidgetProps) {
  const toast = useToast();
  const [copied, setCopied] = useState<string | null>(null);
  const rows = (data?.upcoming_birthdays as BirthdayItem[]) ?? [];
  const copyWish = (b: BirthdayItem) => {
    navigator.clipboard.writeText(
      `Happy Birthday ${b.name}! Wishing you a wonderful year filled with joy, health, and success from everyone at ${b.company}! 🎂🎉`,
    );
    setCopied(b.name);
    toast.success("Greeting copied to clipboard", `Personalized birthday message for ${b.name} is ready to paste.`);
    setTimeout(() => setCopied(null), 3000);
  };
  return (
    <Card icon={Cake} tone="bg-pink-500/10 text-pink-500" title="Upcoming Birthdays"
      description="Celebrating in the next 45 days" link={{ to: "/employees", label: "All" }}>
      {loading ? <ListSkeleton /> : rows.length === 0 ? (
        <Empty icon={Cake} title="No upcoming birthdays" description="No birthdays recorded in the next 45 days." />
      ) : (
        <PeopleList rows={rows} right={(b) => (
          <div className="flex items-center gap-2">
            {b.days_until === 0 ? <span className="badge badge-success animate-pulse font-semibold">Today! 🎉</span>
              : b.days_until === 1 ? <span className="badge badge-warning">Tomorrow</span>
              : <span className="badge badge-neutral text-xs">{format(new Date(b.date), "d MMM")} • {b.days_until}d</span>}
            <button onClick={() => copyWish(b)} title="Copy birthday wish"
              className="rounded-md p-1 text-fg-subtle transition-colors hover:bg-pink-500/10 hover:text-pink-600">
              {copied === b.name ? <Check size={14} className="text-success" /> : <Copy size={13} />}
            </button>
          </div>
        )} />
      )}
    </Card>
  );
}

export function WorkAnniversaries({ data, loading }: WidgetProps) {
  const rows = (data?.upcoming_anniversaries as AnnivItem[]) ?? [];
  return (
    <Card icon={Sparkles} tone="bg-amber-500/10 text-amber-500" title="Work Anniversaries"
      description="Milestone tenures this month" link={{ to: "/employees", label: "All" }}>
      {loading ? <ListSkeleton /> : rows.length === 0 ? (
        <Empty icon={Award} title="No milestones" description="No work anniversaries in the upcoming 45 days." />
      ) : (
        <PeopleList rows={rows} right={(a) => (
          <div className="text-right">
            <span className="badge badge-accent font-semibold">{a.years} {a.years === 1 ? "year" : "years"}</span>
            <p className="mt-0.5 text-[11px] text-fg-subtle">{format(new Date(a.date), "d MMM")}</p>
          </div>
        )} />
      )}
    </Card>
  );
}

export function NewJoiners({ data, loading }: WidgetProps) {
  const rows = (data?.recent_joiners as JoinerItem[]) ?? [];
  return (
    <Card icon={UserPlus} tone="bg-purple-500/10 text-purple-600 dark:text-purple-400" title="Welcome New Joiners"
      description="Recent additions to the team" link={{ to: "/employees", label: "Directory" }}>
      {loading ? <ListSkeleton /> : rows.length === 0 ? (
        <Empty icon={UserPlus} title="No recent joiners" description="New hires will be welcomed here." />
      ) : (
        <PeopleList rows={rows} right={(j) => (
          <span className="badge badge-neutral text-xs">{j.hire_date ? format(new Date(j.hire_date), "d MMM yyyy") : "Recent"}</span>
        )} />
      )}
    </Card>
  );
}

export function TenureMix({ data, loading }: WidgetProps) {
  const t = dict(data?.tenure);
  const brackets = [
    { label: "Under 5 years", value: num(t.under_5_years), color: CHART.leave },
    { label: "5 – 10 years", value: num(t["5_to_10_years"]), color: CHART.late },
    { label: "Over 10 years", value: num(t.over_10_years), color: CHART.present },
  ];
  return (
    <Card icon={Hourglass} tone="bg-sky-500/10 text-sky-600 dark:text-sky-400" title="Tenure mix"
      description="How long people have been with you">
      <div className="px-5 pb-5">
        {loading ? <Skeleton className="h-28 w-full rounded-xl" /> : (
          <>
            <p className="text-2xl font-bold tabular-nums text-fg">{num(t.avg_years)} <span className="text-sm font-medium text-fg-subtle">years on average</span></p>
            <div className="mt-4"><BarList items={brackets} /></div>
          </>
        )}
      </div>
    </Card>
  );
}

/* ── Organisation & compliance ──────────────────────────────────────────── */

export function HeadcountByDepartment({ data, loading }: WidgetProps) {
  const rows = (data?.department_distribution as { department: string; count: number }[]) ?? [];
  return (
    <Card icon={Briefcase} tone="bg-brand-500/10 text-brand-600 dark:text-brand-400" title="Headcount by department"
      description="Your largest departments" link={{ to: "/organization", label: "Organization" }}>
      <div className="flex-1 px-5 pb-5">
        {loading ? <ListSkeleton /> : rows.length === 0
          ? <Empty icon={Briefcase} title="No departments yet" description="Assign people to departments to see the split." />
          : <DepartmentChart items={rows.map((r) => ({ label: r.department, value: r.count }))} />}
      </div>
    </Card>
  );
}

export function HeadcountByCompany({ data, loading }: WidgetProps) {
  const rows = (data?.entity_distribution as { company: string; short_name?: string; count: number }[]) ?? [];
  return (
    <Card icon={Building2} tone="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" title="Headcount by company"
      description="People in each legal entity" link={{ to: "/organization", label: "Organization" }}>
      <div className="flex-1 px-5 pb-5">
        {loading ? <ListSkeleton /> : rows.length === 0
          ? <Empty icon={Building2} title="No people yet" description="Headcount per company appears once people are hired." />
          : <BarList items={rows.map((r) => ({ label: r.short_name || r.company, value: r.count }))} />}
      </div>
    </Card>
  );
}

export function KycCompliance({ data, loading }: WidgetProps) {
  const k = dict(data?.kyc);
  const segments = [
    { label: "Verified", value: num(k.verified), color: CHART.present },
    { label: "Submitted", value: num(k.submitted), color: CHART.leave },
    { label: "Action required", value: num(k.action_required), color: CHART.late },
    { label: "Not submitted", value: num(k.not_submitted), color: CHART.absent },
  ];
  return (
    <Card icon={ShieldCheck} tone="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" title="KYC compliance"
      description="Verification status across your people" link={{ to: "/employees", label: "Employees" }}>
      <div className="flex flex-col items-center gap-5 px-5 pb-5 sm:flex-row">
        {loading ? <Skeleton className="h-[120px] w-[120px] rounded-full" /> : (
          <Donut size={120} thickness={12} segments={segments}>
            <span className="text-xl font-bold tabular-nums text-fg">{num(k.rate_pct)}%</span>
            <span className="text-[11px] text-fg-subtle">verified</span>
          </Donut>
        )}
        <div className="w-full flex-1">
          <Legend items={segments.map((s) => ({ ...s, value: loading ? "–" : s.value }))} />
        </div>
      </div>
    </Card>
  );
}

export function OrgOverview({ data, loading }: WidgetProps) {
  const o = dict(data?.org_summary);
  const facts: { label: string; value: ReactNode; icon: LucideIcon }[] = [
    { label: "Companies", value: num(o.total_entities), icon: Building2 },
    { label: "Departments", value: num(o.total_departments), icon: Briefcase },
    { label: "Locations", value: num(o.total_locations), icon: MapPin },
    { label: "Avg tenure", value: `${num(o.avg_tenure_years)}y`, icon: Hourglass },
    { label: "Separated", value: num(o.separated_count), icon: UserMinus },
  ];
  return (
    <Card icon={Building2} tone="bg-brand-500/10 text-brand-600 dark:text-brand-400" title="Organisation at a glance"
      description="The shape of your organisation" link={{ to: "/organization", label: "Organization" }}>
      <div className="grid grid-cols-2 gap-3 px-5 pb-5 sm:grid-cols-3">
        {facts.map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-xl border border-line bg-surface-raised/40 px-3 py-3">
            <p className="flex items-center gap-1.5 text-[11px] text-fg-subtle"><Icon size={12} /> {label}</p>
            {loading ? <Skeleton className="mt-1.5 h-6 w-12" /> : <p className="mt-1 text-xl font-bold tabular-nums text-fg">{value}</p>}
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ── Workforce movement ─────────────────────────────────────────────────── */

export function KpiNewJoiners({ data, loading }: WidgetProps) {
  const now = num(dict(data?.month).new_hires);
  const last = num(dict(data?.trends).new_hires_last_month);
  return <StatCard iconTone="green" label="New joiners" icon={UserPlus} loading={loading} value={now} delta={now - last} hint="vs last month" />;
}

export function KpiExits({ data, loading }: WidgetProps) {
  const t = dict(data?.trends);
  const now = num(t.exits_this_month);
  return (
    <StatCard iconTone="red" label="Exits" icon={LogOut} loading={loading} value={now}
      delta={now - num(t.exits_last_month)} invertDelta hint="vs last month" />
  );
}

export function KpiOnNotice({ data, loading }: WidgetProps) {
  const n = num(dict(data?.headcount).on_notice);
  return <StatCard iconTone="orange" label="On notice" icon={Hourglass} loading={loading} value={n} hint={n === 0 ? "nobody serving notice" : "serving notice"} />;
}

export function KpiAvgAttendance({ data, loading }: WidgetProps) {
  const a = dict(data?.attendance_30d);
  const now = typeof a.avg_present_pct === "number" ? a.avg_present_pct : null;
  const prev = typeof a.previous_pct === "number" ? a.previous_pct : null;
  return (
    <StatCard iconTone="teal" label="Avg. attendance" icon={UserCheck} loading={loading} value={now === null ? "–" : `${now}%`}
      delta={now !== null && prev !== null ? Math.round((now - prev) * 10) / 10 : undefined} deltaSuffix=" pt"
      hint={now === null ? "no attendance recorded yet" : "last 30 days"} />
  );
}

export function KpiVacancies({ data, loading }: WidgetProps) {
  const v = dict(data?.vacancies);
  return (
    <StatCard iconTone="purple" label="Vacancies" icon={Armchair} loading={loading} value={num(v.vacancies)}
      hint={num(v.positions) === 0 ? "no positions with a headcount limit" : `${num(v.filled)} of ${num(v.capacity)} seats filled`} />
  );
}

/* ── Action centre ──────────────────────────────────────────────────────── */

const ACTION_ICONS: Record<string, LucideIcon> = {
  leave_approvals: Umbrella,
  corrections: FilePenLine,
  overtime: Timer,
  personnel_actions: ListChecks,
  failed_actions: TriangleAlert,
  kyc: ShieldCheck,
  onboarding: ClipboardCheck,
  statutory: IdCard,
  passports: Plane,
};

interface ActionItem { key: string; label: string; count: number; link: string }

export function ActionCentre({ data, loading }: WidgetProps) {
  const items = (data?.action_centre as ActionItem[]) ?? [];
  const waiting = items.filter((i) => i.count > 0);
  const total = waiting.reduce((n, i) => n + i.count, 0);
  return (
    <div className="card flex h-full flex-col">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-danger/10 text-danger"><Inbox size={16} /></div>
          <div>
            <h3 className="card-title">Action centre</h3>
            <p className="card-desc">What’s waiting on HR</p>
          </div>
        </div>
        {total > 0 && <span className="badge badge-neutral">{total}</span>}
      </div>
      {loading ? <ListSkeleton /> : waiting.length === 0 ? (
        <Empty icon={Check} title="All caught up" description="Nothing is waiting on HR right now." />
      ) : (
        <ul className="flex-1 divide-y divide-line border-t border-line">
          {waiting.map((item) => {
            const Icon = ACTION_ICONS[item.key] ?? Inbox;
            return (
              <li key={item.key}>
                <Link data-action={item.key} to={item.link} className="flex items-center gap-3 px-5 py-2.5 text-[13px] transition-colors hover:bg-muted/40">
                  <span data-action-icon className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-fg/[0.06] text-fg-subtle"><Icon size={14} /></span>
                  <span className="min-w-0 flex-1 truncate text-fg">{item.label}</span>
                  <span data-action-count className="badge badge-warning tabular-nums">{item.count}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ── Lifecycle, exits, highlights, scheduled changes ────────────────────── */

function StatRows({ rows }: { rows: { label: string; value: ReactNode }[] }) {
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="flex items-center justify-between gap-6 text-[13px]">
          <span className="text-fg-muted">{r.label}</span>
          <span className="font-medium tabular-nums text-fg">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

export function EmployeeLifecycle({ data, loading }: WidgetProps) {
  const l = dict(data?.lifecycle);
  const longest = (l.longest_on_probation as (PersonRow & { months: number })[]) ?? [];
  return (
    <Card icon={RefreshCw} tone="bg-brand-500/10 text-brand-600 dark:text-brand-400" title="Employee lifecycle"
      description="Where people are in their employment" link={{ to: "/employees", label: "Employees" }}>
      <div className="px-5 pb-4">
        {loading ? <Skeleton className="h-32 w-full rounded-xl" /> : (
          <StatRows rows={[
            { label: "On probation", value: num(l.on_probation) },
            { label: "On notice", value: num(l.on_notice) },
            { label: "On hold", value: num(l.on_hold) },
            { label: "Confirmed this month", value: num(l.confirmed_this_month) },
            { label: "Promoted this month", value: num(l.promoted_this_month) },
            { label: "Transferred this month", value: num(l.transferred_this_month) },
          ]} />
        )}
      </div>
      {!loading && longest.length > 0 && (
        <>
          <p className="eyebrow px-5 pb-1">Longest on probation</p>
          <PeopleList rows={longest} right={(p) => <span className="badge badge-neutral text-xs">{p.months} mo</span>} />
        </>
      )}
    </Card>
  );
}

export function ExitOverview({ data, loading }: WidgetProps) {
  const x = dict(data?.exits);
  const boxes = [
    { label: "This month", value: num(x.exits_this_month) },
    { label: "Last month", value: num(x.exits_last_month) },
    { label: "Last 90 days", value: num(x.exits_last_90_days) },
    { label: "On notice", value: num(x.on_notice) },
  ];
  return (
    <Card icon={DoorOpen} tone="bg-danger/10 text-danger" title="Exit overview"
      description="Separations and attrition" link={{ to: "/employees", label: "Employees" }}>
      <div className="px-5 pb-5">
        {loading ? <Skeleton className="h-32 w-full rounded-xl" /> : (
          <>
            <div className="grid grid-cols-2 gap-3">
              {boxes.map((b) => (
                <div key={b.label} className="rounded-xl border border-line bg-surface-raised/40 px-3 py-3">
                  <p className="text-[11px] text-fg-subtle">{b.label}</p>
                  <p className="mt-1 text-xl font-bold tabular-nums text-fg">{b.value}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[13px] text-fg-muted">
              <span className="font-semibold tabular-nums text-fg">{num(x.attrition_12m_pct)}%</span> attrition over 12 months
              <span className="text-fg-subtle"> · {num(x.exits_last_12_months)} separations against today’s headcount</span>
            </p>
          </>
        )}
      </div>
    </Card>
  );
}

interface HighlightPerson extends PersonRow { years?: number }

export function TodaysHighlights({ data, loading }: WidgetProps) {
  const toast = useToast();
  const h = dict(data?.highlights_today);
  const groups: { key: string; label: string; icon: LucideIcon; people: HighlightPerson[] }[] = [
    { key: "company_anniversaries", label: "Company anniversaries today", icon: Cake, people: (h.company_anniversaries as HighlightPerson[]) ?? [] },
    { key: "joining", label: "Joining today", icon: UserPlus, people: (h.joining as HighlightPerson[]) ?? [] },
    { key: "exiting", label: "Leaving today", icon: UserMinus, people: (h.exiting as HighlightPerson[]) ?? [] },
    { key: "birthdays", label: "Birthdays today", icon: Cake, people: (h.birthdays as HighlightPerson[]) ?? [] },
    { key: "anniversaries", label: "Work anniversaries today", icon: Award, people: (h.anniversaries as HighlightPerson[]) ?? [] },
  ];
  const any = groups.some((g) => g.people.length > 0);
  const wish = (p: HighlightPerson, key: string) => {
    navigator.clipboard.writeText(key === "company_anniversaries"
      ? `Happy company anniversary to ${p.name}! Celebrating ${p.years} years together. 🎉`
      : key === "birthdays"
      ? `Happy Birthday ${p.name}! Wishing you a wonderful year ahead from everyone at ${p.company}! 🎂`
      : `Congratulations ${p.name} on ${p.years} ${p.years === 1 ? "year" : "years"} with ${p.company}! Thank you for all you do. 🎉`);
    toast.success("Message copied", `Ready to paste for ${p.name}.`);
  };
  return (
    <Card icon={Gift} tone="bg-pink-500/10 text-pink-500" title="Today’s highlights" description={format(new Date(), "EEEE, d MMM")}>
      {loading ? <ListSkeleton /> : !any ? (
        <Empty icon={Gift} title="A quiet day" description="Nobody is joining, leaving or celebrating today." />
      ) : (
        <div className="flex-1 space-y-4 px-5 pb-5">
          {groups.filter((g) => g.people.length > 0).map((g) => (
            <section key={g.key}>
              <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-fg-muted">
                <g.icon size={13} /> {g.label} <span className="badge badge-neutral">{g.people.length}</span>
              </p>
              <ul className="space-y-1">
                {g.people.map((p, i) => (
                  <li key={i} className="flex items-center justify-between gap-2 text-[13px]">
                    <span className="min-w-0 truncate text-fg">
                      {p.name}{(g.key === "anniversaries" || g.key === "company_anniversaries") && p.years ? <span className="text-fg-subtle"> · {p.years}y</span> : null}
                    </span>
                    {(g.key === "birthdays" || g.key === "anniversaries" || g.key === "company_anniversaries") && (
                      <button onClick={() => wish(p, g.key)} className="link shrink-0 text-xs">
                        {g.key === "birthdays" ? "Copy wish" : "Copy note"}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Card>
  );
}

interface ScheduledChange extends PersonRow { type: string; effective_date: string; days_until: number }

const CHANGE_LABEL: Record<string, string> = {
  TRANSFER: "Transfer", PROMOTION: "Promotion", DEMOTION: "Demotion", CONFIRM: "Confirmation",
  EXTEND_PROBATION: "Probation extended", PLACE_ON_NOTICE: "Notice", SEPARATION: "Separation",
  REHIRE: "Rehire", CHANGE_MANAGER: "Manager change", CHANGE_GRADE: "Grade change",
  CHANGE_COST_CENTRE: "Cost centre change", HIRE: "Hire",
};

export function ScheduledChanges({ data, loading }: WidgetProps) {
  const rows = (data?.scheduled_changes as ScheduledChange[]) ?? [];
  return (
    <Card icon={CalendarClock} tone="bg-info/10 text-info" title="Scheduled changes"
      description="Taking effect in the next 30 days" link={{ to: "/employees", label: "Employees" }}>
      {loading ? <ListSkeleton /> : rows.length === 0 ? (
        <Empty icon={CalendarClock} title="Nothing scheduled" description="No personnel changes take effect in the next 30 days." />
      ) : (
        <PeopleList rows={rows} right={(c) => (
          <div className="text-right">
            <span className={`badge ${c.type === "SEPARATION" ? "badge-warning" : "badge-neutral"}`}>{CHANGE_LABEL[c.type] ?? c.type}</span>
            <p className="mt-0.5 text-[11px] text-fg-subtle">
              {c.days_until <= 0 ? "Today" : c.days_until === 1 ? "Tomorrow" : `${format(new Date(c.effective_date), "d MMM")} · in ${c.days_until}d`}
            </p>
          </div>
        )} />
      )}
    </Card>
  );
}

/* ── Compliance, workforce mix, leave by department, shortcuts ──────────── */

export function StatutoryIds({ data, loading }: WidgetProps) {
  const s = dict(data?.statutory);
  const employees = num(s.employees);
  return (
    <Card icon={IdCard} tone="bg-amber-500/10 text-amber-600 dark:text-amber-400" title="Statutory IDs"
      description="Numbers not yet on file in KYC" link={{ to: "/employees", label: "Employees" }}>
      <div className="px-5 pb-5">
        {loading ? <Skeleton className="h-28 w-full rounded-xl" /> : (
          <>
            <StatRows rows={[
              { label: "UAN not on file", value: `${num(s.missing_uan)} of ${employees}` },
              { label: "PF number not on file", value: `${num(s.missing_pf)} of ${employees}` },
              { label: "ESI number not on file", value: `${num(s.missing_esi)} of ${employees}` },
              { label: "Passports expiring in 90 days", value: num(s.passports_expiring) },
            ]} />
            <p className="mt-4 text-[11px] text-fg-subtle">
              Counts missing IDs only — whether someone is covered by PF or ESI depends on their wages, which aren’t held here.
            </p>
          </>
        )}
      </div>
    </Card>
  );
}

const TYPE_COLORS = [CHART.leave, CHART.present, CHART.late, CHART.brand, CHART.absent];
const titleCase = (s: string) => s.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function EmployeeType({ data, loading }: WidgetProps) {
  const types = (data?.worker_types as { worker_type: string; count: number }[]) ?? [];
  const total = types.reduce((n, t) => n + t.count, 0);
  const segments = types.map((t, i) => ({ label: titleCase(t.worker_type), value: t.count, color: TYPE_COLORS[i % TYPE_COLORS.length] }));
  return (
    <Card icon={ChartPie} tone="bg-sky-500/10 text-sky-600 dark:text-sky-400" title="Employee type" description="How your people are engaged">
      <div className="flex flex-col items-center gap-5 px-5 pb-5 sm:flex-row">
        {loading ? <Skeleton className="h-[120px] w-[120px] rounded-full" /> : total === 0 ? (
          <Empty icon={ChartPie} title="No people yet" description="Worker types appear once people are hired." />
        ) : (
          <>
            <Donut size={120} thickness={12} segments={segments}>
              <span className="text-xl font-bold tabular-nums text-fg">{total}</span>
              <span className="text-[11px] text-fg-subtle">people</span>
            </Donut>
            <div className="w-full flex-1">
              <Legend items={segments.map((s) => ({ ...s, value: `${Math.round((s.value / total) * 100)}%` }))} />
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export function LeaveByDepartment({ data, loading }: WidgetProps) {
  const rows = (data?.leave_by_department as { department: string; days: number; days_per_person: number }[]) ?? [];
  return (
    <Card icon={Umbrella} tone="bg-info/10 text-info" title="Leave by department"
      description="Approved days per person, last 90 days" link={{ to: "/leave", label: "Leave" }}>
      <div className="flex-1 px-5 pb-5">
        {loading ? <ListSkeleton /> : rows.length === 0
          ? <Empty icon={Umbrella} title="No leave taken" description="Approved leave in the last 90 days appears here." />
          : <DepartmentProgress items={rows.map((r) => ({ label: r.department, value: r.days_per_person }))} formatValue={(v) => `${v}d`} />}
      </div>
    </Card>
  );
}

const SHORTCUTS: { label: string; to: string; icon: LucideIcon }[] = [
  { label: "Add employee", to: "/employees?new=1", icon: ActionUserPlus },
  { label: "Apply leave", to: "/leave?new=1", icon: Umbrella },
  { label: "Request correction", to: "/corrections?new=1", icon: ActionCorrection },
  { label: "Leave approvals", to: "/leave?tab=approvals", icon: Check },
  { label: "Daily analysis", to: "/daily-analysis", icon: CalendarClock },
  { label: "Onboarding", to: "/onboarding", icon: ClipboardCheck },
  { label: "Reports", to: "/reports", icon: ActionReports },
  { label: "Policies", to: "/policy", icon: ShieldCheck },
];

export function QuickActions() {
  return (
    <Card icon={Zap} tone="bg-brand-500/10 text-brand-600 dark:text-brand-400" title="Quick actions" description="Everyday HR tasks">
      <div data-quick-actions className="grid grid-cols-2 gap-2 px-5 pb-5 sm:grid-cols-4">
        {SHORTCUTS.map(({ label, to, icon: Icon }) => (
          <Link key={label} to={to}
            className="flex flex-col items-center gap-1.5 rounded-xl border border-line px-2 py-3 text-center text-xs text-fg-muted transition-colors hover:border-brand-500/40 hover:bg-muted/40 hover:text-fg">
            <Icon size={16} className="text-fg-subtle" />
            <span className="leading-tight">{label}</span>
          </Link>
        ))}
      </div>
    </Card>
  );
}

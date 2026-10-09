/**
 * The HRMS overview: a fixed, at-a-glance layout for HR and admins — the alternative to the
 * customisable widget grid (each person picks one; see DashboardPage). Every figure comes
 * from /v1/dashboard/hr and /v1/leave/applications/summary for the caller's scope, optionally
 * narrowed to one company. Cards for things HRMS doesn't track yet say so rather than
 * showing numbers.
 */
import { Fragment, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Award, BarChart3, BookOpen, Building2, Cake, Calendar,
  CalendarCheck, CalendarClock, ChevronRight, ClipboardCheck, Clock, FileText, GraduationCap,
  Hourglass, IdCard, Inbox, ListChecks, LogOut, Plane, ShieldCheck, Sparkles, Timer, TimerReset,
  TriangleAlert, UserCheck, UserCircle, UserPlus, Users, Umbrella, LayoutGrid, GripVertical, ActionUserPlus,
} from "../icons/ThemeIcons";
import type { LucideIcon } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { dashboardApi } from "../../api/dashboard";
import type { DashboardLayout } from "../../api/dashboard";
import { Sheet } from "../ui/Overlay";
import { DndContext, KeyboardSensor, PointerSensor, TouchSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { leaveApi } from "../../api/leave";
import { useAuth } from "../../context/AuthContext";
import { DepartmentColumns, DepartmentProgress, Donut } from "../ui/Charts";
import { CHART } from "../ui/chartPalette";
import { useTheme } from "../../context/ThemeContext";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { Avatar } from "../ui/Avatar";
import { useToast, errorMessage } from "../ui/Toast";

type Dict = Record<string, unknown>;
const num = (v: unknown, fallback = 0) => (typeof v === "number" ? v : fallback);
const dict = (v: unknown) => (v && typeof v === "object" ? (v as Dict) : {});
const list = <T,>(v: unknown) => (Array.isArray(v) ? (v as T[]) : []);
const pct = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 1000) / 10 : 0);



/* ── Shared pieces ──────────────────────────────────────────────────────── */

function Panel({ title, span, link, badge, children, footer }: {
  title: ReactNode;
  span: string;
  link?: { to: string; label: string };
  badge?: ReactNode;
  children: ReactNode;
  footer?: { to: string; label: string };
}) {
  return (
    <div className={`${span} card flex flex-col`}>
      <div className="card-header border-b border-line/60">
        <div className="flex items-center gap-2"><h3 className="card-title">{title}</h3>{badge}</div>
        {link && <Link to={link.to} className="text-xs font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400">{link.label}</Link>}
      </div>
      <div className="flex flex-1 flex-col">{children}</div>
      {footer && (
        <div className="border-t border-line/60 p-3 text-right">
          <Link to={footer.to} className="flex items-center justify-end gap-1 text-xs font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400">
            {footer.label} <ChevronRight size={13} />
          </Link>
        </div>
      )}
    </div>
  );
}

function Loading({ rows = 3 }: { rows?: number }) {
  return <div className="space-y-2.5 p-4">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}</div>;
}

function NotTracked({ icon, what }: { icon: LucideIcon; what: string }) {
  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <EmptyState icon={icon} title="Not tracked yet" description={`${what} isn’t recorded in HRMS yet, so there’s nothing to show.`} className="py-6" />
    </div>
  );
}



/* ── The overview ───────────────────────────────────────────────────────── */

interface Person { name: string; department: string; company: string; years?: number }
interface ActionItem { key: string; label: string; count: number; link: string }
interface Change extends Person { type: string; effective_date: string; days_until: number }
interface Joiner extends Person { hire_date?: string; designation?: string | null }

const ACTION_ICONS: Record<string, LucideIcon> = {
  leave_approvals: CalendarCheck, corrections: TimerReset, overtime: Timer,
  personnel_actions: ListChecks, failed_actions: TriangleAlert, kyc: ShieldCheck,
  onboarding: ClipboardCheck, statutory: IdCard, passports: Plane,
};
const URGENT = new Set(["failed_actions", "leave_approvals", "corrections"]);
const CHANGE_LABEL: Record<string, string> = {
  TRANSFER: "Transfer", PROMOTION: "Promotion", DEMOTION: "Demotion", CONFIRM: "Confirmation",
  EXTEND_PROBATION: "Probation extension", PLACE_ON_NOTICE: "Notice", SEPARATION: "Separation",
  REHIRE: "Rehire", CHANGE_MANAGER: "Manager change", CHANGE_GRADE: "Grade change",
  CHANGE_COST_CENTRE: "Cost centre change", CHANGE_JOB: "Designation change", HIRE: "Hire",
};
const titleCase = (s: string) => s.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const TYPE_COLORS = [CHART.leave, CHART.present, CHART.late, CHART.brand, CHART.absent];

type TaskTab = "All" | "Overdue" | "Due soon" | "Upcoming";
interface Task { id: string; title: string; details: string; due: string; tab: Exclude<TaskTab, "All">; link: string }

export function HRMSDashboardView() {
  const { user } = useAuth();
  const { colorTheme } = useTheme();
  const midnight = colorTheme === "midnight-blue";
  const toast = useToast();
  const [company, setCompany] = useState("");
  const [taskTab, setTaskTab] = useState<TaskTab>("All");
  const [customizing, setCustomizing] = useState(false);
  const layout = useQuery({ queryKey: ["dash-layout", "overview"], queryFn: () => dashboardApi.layout("overview") });
  const companies = user?.legalEntities ?? [];

  const hr = useQuery({
    // Only the sections the visible cards need; the layout works them out.
    queryKey: ["dash-hr", "overview", layout.data?.sections, company || "all"],
    queryFn: () => dashboardApi.hr(layout.data!.sections, company || undefined),
    enabled: !!layout.data,
    // Keep the cards on screen while a new card selection or company refetches.
    placeholderData: keepPreviousData,
  });
  const canSeeLeave = !!user?.permissions.some((p) => p === "*" || p === "leave.read" || p === "leave.approve");
  const leave = useQuery({
    queryKey: ["leave-applications", "summary", company || "all"],
    queryFn: () => leaveApi.applicationSummary(company || undefined),
    enabled: canSeeLeave && !!layout.data?.widgets.some((w) => w.widget === "leave"),
    placeholderData: keepPreviousData,
  });

  const d = hr.data;
  const loading = hr.isPending;
  const head = dict(d?.headcount);
  const today = dict(d?.today);
  const exits = dict(d?.exits);
  const stat = dict(d?.statutory);
  const life = dict(d?.lifecycle);
  const highlights = dict(d?.highlights_today);
  const actions = list<ActionItem>(d?.action_centre);
  const changes = list<Change>(d?.scheduled_changes);

  const total = num(head.total);
  const present = num(today.present);
  const late = num(today.late);
  const absent = num(today.absent);
  const onLeave = num(today.on_leave);

  const waiting = actions.filter((a) => a.count > 0);
  const failed = actions.find((a) => a.key === "failed_actions")?.count ?? 0;
  const tasks: Task[] = [
    ...(failed > 0 ? [{ id: "failed", title: "Scheduled changes that failed", details: `${failed} to fix or cancel`, due: "Overdue", tab: "Overdue" as const, link: "/employees" }] : []),
    ...waiting.filter((a) => a.key !== "failed_actions" && a.key !== "statutory" && a.key !== "passports")
      .map((a) => ({ id: a.key, title: a.label, details: `${a.count} waiting`, due: "Now", tab: "Due soon" as const, link: a.link })),
    ...changes.map((c, i) => ({
      id: `change-${i}`,
      title: `${CHANGE_LABEL[c.type] ?? titleCase(c.type)}: ${c.name}`,
      details: `${c.department} · ${c.company}`,
      due: c.days_until <= 0 ? "Today" : c.days_until === 1 ? "Tomorrow" : format(new Date(c.effective_date), "d MMM yyyy"),
      tab: (c.days_until <= 7 ? "Due soon" : "Upcoming") as Task["tab"],
      link: "/employees",
    })),
  ];
  const tabCount = (t: TaskTab) => (t === "All" ? tasks.length : tasks.filter((x) => x.tab === t).length);
  const shownTasks = taskTab === "All" ? tasks : tasks.filter((t) => t.tab === taskTab);

  const byStatus = leave.data?.by_status ?? {};
  const statusCount = (match: (s: string) => boolean) =>
    Object.entries(byStatus).reduce((n, [s, c]) => (match(s) ? n + c : n), 0);
  const leaveDept = list<{ department: string; days_per_person: number }>(d?.leave_by_department).slice(0, 5);
  const leaveMax = Math.max(...leaveDept.map((x) => x.days_per_person), 0.1);
  const departments = list<{ department: string; count: number }>(d?.department_distribution);
  const deptMax = Math.max(...departments.map((x) => x.count), 1);
  const types = list<{ worker_type: string; count: number }>(d?.worker_types);
  const typeTotal = types.reduce((n, t) => n + t.count, 0);
  const joiners = list<Joiner>(d?.recent_joiners);

  const copy = (text: string, who: string) => {
    navigator.clipboard.writeText(text);
    toast.success("Message copied", `Paste it to send to ${who}.`);
  };
  const highlightRows: { key: string; icon: LucideIcon; tone: string; label: string; people: Person[]; action?: (p: Person[]) => void; actionLabel?: string }[] = [
    {
      key: "company_anniversaries", icon: Cake, tone: "bg-pink-50 text-pink-600 dark:bg-pink-950 dark:text-pink-400", label: "company anniversaries today",
      people: list<Person>(highlights.company_anniversaries), actionLabel: "Copy wish",
      action: (ps) => copy(`Happy company anniversary to ${ps.map((p) => `${p.name} (${p.years} years)`).join(", ")}! Celebrating another year together. 🎉`, ps.map((p) => p.name).join(", ")),
    },
    { key: "joining", icon: UserPlus, tone: "bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400", label: "joining today", people: list<Person>(highlights.joining) },
    { key: "exiting", icon: LogOut, tone: "bg-rose-50 text-rose-600 dark:bg-rose-950 dark:text-rose-400", label: "leaving today", people: list<Person>(highlights.exiting) },
    {
      key: "birthdays", icon: Cake, tone: "bg-pink-50 text-pink-600 dark:bg-pink-950 dark:text-pink-400", label: "birthdays today",
      people: list<Person>(highlights.birthdays), actionLabel: "Copy wish",
      action: (ps) => copy(`Happy birthday ${ps.map((p) => p.name).join(", ")}! Wishing you a wonderful year ahead. 🎂`, ps.map((p) => p.name).join(", ")),
    },
    {
      key: "anniversaries", icon: Award, tone: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400", label: "work anniversaries today",
      people: list<Person>(highlights.anniversaries), actionLabel: "Copy note",
      action: (ps) => copy(`Congratulations ${ps.map((p) => `${p.name} (${p.years}y)`).join(", ")} on your work anniversary! 🎉`, ps.map((p) => p.name).join(", ")),
    },
  ];

  const order = layout.data?.widgets.map((w) => w.widget) ?? [];



  const cards: Record<string, ReactNode> = {
    attendance: (
          <Panel span="col-span-12 lg:col-span-4" title="Attendance Overview (Today)" badge={<span className="badge badge-neutral text-xs">Today</span>}>
            {loading ? <Loading rows={4} /> : (
              <div className="flex flex-1 flex-col justify-between space-y-4 p-5">
                <div className="flex items-center justify-center py-2">
                  <Donut size={176} thickness={16} segments={[
                    { label: "Present", value: Math.max(present - late, 0), color: CHART.present },
                    { label: "Late", value: late, color: CHART.late },
                    { label: "Absent", value: absent, color: CHART.absent },
                    { label: "On leave", value: onLeave, color: CHART.leave },
                  ]}>
                    <span className="text-2xl font-extrabold tracking-tight text-fg">{pct(present, total)}%</span>
                    <span className="text-[11px] font-medium text-fg-subtle">{midnight ? "Present %" : "Present"}</span>
                  </Donut>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {[
                    { label: "Present", value: present, dot: "bg-emerald-500" },
                    { label: "Absent", value: absent, dot: "bg-rose-500" },
                    { label: "Late", value: late, dot: "bg-amber-500" },
                    { label: "On Leave", value: onLeave, dot: "bg-blue-500" },
                  ].map((r) => (
                    <div key={r.label} className="flex items-center justify-between rounded-lg bg-muted/40 px-2.5 py-1.5">
                      <span className="flex items-center gap-1.5 font-medium text-fg"><span className={`h-2 w-2 rounded-full ${r.dot}`} /> {r.label}</span>
                      <span className="font-semibold text-fg">{r.value} <span className="font-normal text-fg-subtle">({pct(r.value, total)}%)</span></span>
                    </div>
                  ))}
                </div>
                <div className="border-t border-line/60 pt-3 text-center text-xs font-semibold text-fg-muted">Total Employees : {total}</div>
              </div>
            )}
          </Panel>
    ),
    leave: (
          <Panel span="col-span-12 lg:col-span-4" title="Leave Overview" link={{ to: "/leave", label: "Open Leave" }} footer={{ to: "/leave", label: "View all leave" }}>
            {!canSeeLeave ? (
              <div className="flex flex-1 items-center justify-center p-4">
                <EmptyState icon={Umbrella} title="No leave access" description="Your role doesn’t include leave records." className="py-6" />
              </div>
            ) : leave.isPending || loading ? <Loading rows={4} /> : (
              <div className="flex flex-1 flex-col space-y-4 p-5">
                <div className="grid grid-cols-4 gap-2 text-center">
                  {[
                    { label: "Pending", value: statusCount((s) => s.includes("PENDING")), cls: "border-amber-200/60 bg-amber-50/60 text-amber-600 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-400" },
                    { label: "Approved", value: statusCount((s) => s === "APPROVED"), cls: "border-emerald-200/60 bg-emerald-50/60 text-emerald-600 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-400" },
                    { label: "Rejected", value: statusCount((s) => s === "REJECTED"), cls: "border-rose-200/60 bg-rose-50/60 text-rose-600 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-400" },
                    { label: "Cancelled", value: statusCount((s) => s === "CANCELLED"), cls: "border-zinc-200/60 bg-zinc-50/60 text-zinc-600 dark:border-zinc-700/40 dark:bg-zinc-800/30 dark:text-zinc-400" },
                  ].map((b) => (
                    <div key={b.label} className={`rounded-lg border p-2 ${b.cls}`}>
                      <p className="text-lg font-bold">{b.value}</p>
                      <p className="text-[11px] font-medium text-fg-muted">{b.label}</p>
                    </div>
                  ))}
                </div>
                <div className="space-y-2.5 pt-2">
                  <p className="text-xs font-semibold text-fg-muted">Leave days per person by department · last 90 days</p>
                  {leaveDept.length === 0 ? <p className="text-xs text-fg-subtle">No approved leave in the last 90 days.</p> : midnight ? <DepartmentProgress items={leaveDept.map((x) => ({ label: x.department, value: x.days_per_person }))} formatValue={(v) => `${v}d`} /> : leaveDept.map((x) => (
                    <div key={x.department} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="font-medium text-fg">{x.department}</span>
                        <span className="font-semibold text-fg">{x.days_per_person}d</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-brand-600 transition-all duration-700 dark:bg-brand-500" style={{ width: `${(x.days_per_person / leaveMax) * 100}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Panel>
    ),
    action_centre: (
          <Panel span="col-span-12 lg:col-span-4" title="Action Centre"
            badge={waiting.length > 0 ? <span className="inline-flex items-center justify-center rounded-full bg-rose-500 px-2 py-0.5 text-[11px] font-bold text-white">{waiting.reduce((n, a) => n + a.count, 0)}</span> : undefined}>
            {loading ? <Loading rows={5} /> : waiting.length === 0 ? (
              <div className="flex flex-1 items-center justify-center p-4">
                <EmptyState icon={Inbox} title="All caught up" description="Nothing is waiting on HR right now." className="py-6" />
              </div>
            ) : (
              <ul className="flex-1 divide-y divide-line/50 p-3 text-xs">
                {waiting.map((a) => {
                  const Icon = ACTION_ICONS[a.key] ?? Inbox;
                  return (
                    <li key={a.key}>
                      <Link data-action={a.key} to={a.link} className="flex items-center justify-between rounded-lg px-2 py-2 transition-colors hover:bg-muted/40">
                        <span className="flex items-center gap-2.5"><Icon data-action-icon size={15} className="text-fg-subtle" /><span className="font-medium text-fg">{a.label}</span></span>
                        <span data-action-count className={`rounded-full px-2 py-0.5 font-bold ${URGENT.has(a.key) ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300" : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"}`}>{a.count}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
    ),
    highlights: (
          <Panel span="col-span-12 lg:col-span-4" title={<span className="flex items-center gap-2"><Sparkles size={16} className="text-brand-500" />Today’s Highlights</span>}
            badge={<span className="badge badge-neutral text-xs">Today</span>}>
            {loading ? <Loading rows={4} /> : (
              <div className="flex-1 space-y-3 p-4">
                {highlightRows.map((r) => (
                  <div key={r.key} className="flex items-center justify-between rounded-xl border border-line bg-surface p-2.5 transition-colors hover:bg-muted/40">
                    <div className="flex min-w-0 items-center gap-3">
                      <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${r.tone}`}><r.icon size={16} /></div>
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-fg">{String(r.people.length).padStart(2, "0")} {r.label}</p>
                        <p className="truncate text-[11px] text-fg-subtle">{r.people.length === 0 ? "None today" : r.people.slice(0, 3).map((p) => p.name).join(", ") + (r.people.length > 3 ? ` +${r.people.length - 3}` : "")}</p>
                      </div>
                    </div>
                    {r.action && r.people.length > 0 && (
                      <button onClick={() => r.action!(r.people)} className="btn-sm shrink-0 rounded-lg bg-brand-500/10 px-2.5 font-semibold text-brand-600 hover:bg-brand-500/20 dark:text-brand-400">{r.actionLabel}</button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>
    ),
    quick_actions: (
          <Panel span="col-span-12 lg:col-span-8" title="Quick Actions" badge={<span className="text-xs text-fg-subtle">Frequently used HR actions</span>}>
            <div data-quick-actions className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
              {[
                { label: "Add Employee", icon: ActionUserPlus, to: "/employees?new=1" },
                { label: "Apply Leave", icon: Umbrella, to: "/leave?new=1" },
                { label: "Regularize Attendance", icon: TimerReset, to: "/corrections?new=1" },
                { label: "Leave Approvals", icon: CalendarCheck, to: "/leave?tab=approvals" },
                { label: "Onboarding", icon: ClipboardCheck, to: "/onboarding" },
                { label: "Daily Analysis", icon: CalendarClock, to: "/daily-analysis" },
                { label: "Employee Documents", icon: FileText, to: "/employees" },
                { label: "View Reports", icon: BarChart3, to: "/reports" },
              ].map((qa) => (
                <Link key={qa.label} to={qa.to}
                  className="group flex cursor-pointer flex-col items-center justify-center rounded-xl border border-line bg-surface p-3.5 text-center transition-all hover:border-brand-500/60 hover:bg-brand-500/5">
                  <div className="grid h-10 w-10 place-items-center rounded-lg bg-muted text-brand-600 transition-colors group-hover:bg-brand-600 group-hover:text-white dark:text-brand-400"><qa.icon size={18} /></div>
                  <span className="mt-2 text-xs font-semibold text-fg group-hover:text-brand-600 dark:group-hover:text-brand-400">{qa.label}</span>
                </Link>
              ))}
            </div>
          </Panel>
    ),
    lifecycle: (
          <Panel span="col-span-12 sm:col-span-6 lg:col-span-4" title="Employee Lifecycle" link={{ to: "/employees", label: "View All" }}>
            {loading ? <Loading /> : (
              <div className="flex-1 space-y-3 p-4">
                {[
                  { label: "On Probation", count: num(life.on_probation), icon: Clock, color: "bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-400" },
                  { label: "On Notice", count: num(life.on_notice), icon: Hourglass, color: "bg-rose-50 text-rose-600 dark:bg-rose-950 dark:text-rose-400" },
                  { label: "Confirmed This Month", count: num(life.confirmed_this_month), icon: UserCheck, color: "bg-emerald-50 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400" },
                  { label: "Promoted This Month", count: num(life.promoted_this_month), icon: Award, color: "bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400" },
                ].map((it) => (
                  <div key={it.label} className="flex items-center justify-between rounded-xl border border-line bg-surface p-3">
                    <div className="flex items-center gap-3">
                      <div className={`grid h-8 w-8 place-items-center rounded-lg ${it.color}`}><it.icon size={16} /></div>
                      <span className="text-xs font-semibold text-fg">{it.label}</span>
                    </div>
                    <span className="text-base font-bold text-fg">{it.count}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>
    ),
    training: (
          <Panel span="col-span-12 sm:col-span-6 lg:col-span-4" title="Training Overview">
            <NotTracked icon={GraduationCap} what="Training" />
          </Panel>
    ),
    exits: (
          <Panel span="col-span-12 sm:col-span-6 lg:col-span-4" title="Exit Overview" link={{ to: "/employees", label: "View Employees" }}>
            {loading ? <Loading rows={4} /> : (
              <div className="flex-1 space-y-2 p-4">
                {[
                  { label: "Exits This Month", value: num(exits.exits_this_month), icon: LogOut, color: "text-rose-500" },
                  { label: "Exits, Last 90 Days", value: num(exits.exits_last_90_days), icon: Calendar, color: "text-orange-500" },
                  { label: "Notice Period", value: num(exits.on_notice), icon: Clock, color: "text-amber-500" },
                  { label: "Attrition, 12 Months", value: `${num(exits.attrition_12m_pct)}%`, icon: BarChart3, color: "text-purple-500" },
                ].map((it) => (
                  <div key={it.label} className="flex items-center justify-between rounded-lg border border-line bg-surface p-2.5 text-xs">
                    <span className="flex items-center gap-2"><it.icon size={15} className={it.color} /><span className="font-medium text-fg">{it.label}</span></span>
                    <span className="font-bold text-fg">{it.value}</span>
                  </div>
                ))}
                <p className="pt-1 text-[11px] text-fg-subtle">Clearance and full &amp; final settlement aren’t tracked yet.</p>
              </div>
            )}
          </Panel>
    ),
    departments: (
          <Panel span="col-span-12 lg:col-span-6" title="Department-wise Headcount" link={{ to: "/organization", label: "Organization" }}>
            {loading ? <Loading rows={4} /> : departments.length === 0 ? (
              <div className="flex flex-1 items-center justify-center p-4">
                <EmptyState icon={Building2} title="No departments yet" description="Assign people to departments to see the split." className="py-6" />
              </div>
            ) : (
              <div className="flex flex-1 flex-col justify-between p-5">
                {midnight ? <DepartmentColumns items={departments.map((x) => ({ label: x.department, value: x.count }))} /> : <div className="flex h-52 w-full items-end justify-between gap-3 border-b border-line px-2 pb-2 pt-6">
                  {departments.map((x) => (
                    <div key={x.department} className="group flex h-full flex-1 flex-col items-center justify-end gap-2">
                      <span className="text-[11px] font-bold text-fg">{x.count}</span>
                      <div className="flex h-full w-full max-w-[36px] items-end rounded-t-md bg-muted/60">
                        <div className="w-full rounded-t-md bg-brand-600 transition-all duration-500 group-hover:brightness-110 dark:bg-brand-500" style={{ height: `${(x.count / deptMax) * 100}%` }} />
                      </div>
                      <span className="max-w-[64px] truncate text-center text-[11px] font-medium text-fg-subtle" title={x.department}>{x.department}</span>
                    </div>
                  ))}
                </div>}
                <p className="pt-3 text-xs text-fg-subtle">Largest {departments.length} departments by current headcount</p>
              </div>
            )}
          </Panel>
    ),
    employee_type: (
          <Panel span="col-span-12 sm:col-span-6 lg:col-span-3" title="Employee Type">
            {loading ? <Loading rows={4} /> : typeTotal === 0 ? (
              <div className="flex flex-1 items-center justify-center p-4"><EmptyState icon={Users} title="No people yet" className="py-6" /></div>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-between p-5">
                <Donut size={160} thickness={14} segments={types.map((t, i) => ({ label: titleCase(t.worker_type), value: t.count, color: TYPE_COLORS[i % TYPE_COLORS.length] }))}>
                  <span className="text-xl font-bold tracking-tight text-fg">{typeTotal.toLocaleString()}</span>
                  <span className="text-[11px] font-medium text-fg-subtle">Employees</span>
                </Donut>
                <div className="mt-3 w-full space-y-1.5 text-xs">
                  {types.map((t, i) => (
                    <div key={t.worker_type} className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-fg"><span className="h-2 w-2 rounded-full" style={{ background: TYPE_COLORS[i % TYPE_COLORS.length] }} />{titleCase(t.worker_type)}</span>
                      <span className="font-semibold text-fg">{Math.round(pct(t.count, typeTotal))}%</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Panel>
    ),
    compliance: (
          <Panel span="col-span-12 sm:col-span-6 lg:col-span-3" title="Compliance (PF & ESIC)" link={{ to: "/employees", label: "Employees" }}>
            {loading ? <Loading /> : (
              <div className="flex flex-1 flex-col justify-center space-y-3 p-4">
                {[
                  { label: "UAN not on file", value: num(stat.missing_uan), icon: IdCard, cls: "border-blue-200/60 bg-blue-50/50 text-blue-600 dark:border-blue-900/40 dark:bg-blue-950/30 dark:text-blue-400" },
                  { label: "PF number not on file", value: num(stat.missing_pf), icon: FileText, cls: "border-blue-200/60 bg-blue-50/50 text-blue-600 dark:border-blue-900/40 dark:bg-blue-950/30 dark:text-blue-400" },
                  { label: "ESI number not on file", value: num(stat.missing_esi), icon: ShieldCheck, cls: "border-rose-200/60 bg-rose-50/50 text-rose-600 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-400" },
                ].map((b) => (
                  <div key={b.label} className={`flex items-center justify-between rounded-xl border p-3 ${b.cls}`}>
                    <span className="flex items-center gap-2.5"><b.icon size={18} /><span className="text-xs font-medium text-fg">{b.label}</span></span>
                    <span className="text-lg font-bold">{b.value}</span>
                  </div>
                ))}
                <p className="text-[11px] text-fg-subtle">Of {num(stat.employees)} people. Coverage depends on wages, which aren’t held here.</p>
              </div>
            )}
          </Panel>
    ),
    tasks: (
          <Panel span="col-span-12 lg:col-span-6" title={<span className="flex items-center gap-2"><Clock size={16} className="text-brand-500" />HR Tasks / Action Required</span>}>
            <div className="flex items-center gap-1 border-b border-line px-4 pt-2">
              {(["All", "Overdue", "Due soon", "Upcoming"] as TaskTab[]).map((t) => (
                <button key={t} onClick={() => setTaskTab(t)}
                  className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-semibold transition-colors ${taskTab === t ? "border-brand-500 text-brand-600 dark:text-brand-400" : "border-transparent text-fg-subtle hover:text-fg"}`}>
                  <span>{t}</span><span className="rounded-full bg-muted px-1.5 text-[10px] font-normal text-fg-muted">{loading ? "–" : tabCount(t)}</span>
                </button>
              ))}
            </div>
            {loading ? <Loading /> : shownTasks.length === 0 ? (
              <div className="flex flex-1 items-center justify-center p-4"><EmptyState icon={ListChecks} title="Nothing here" description="No tasks in this view." className="py-6" /></div>
            ) : (
              <ul className="flex-1 space-y-2 p-3">
                {shownTasks.map((t) => (
                  <li key={t.id}>
                    <Link to={t.link} className="flex items-center justify-between rounded-lg border border-line bg-surface p-2.5 transition-colors hover:bg-muted/40">
                      <span className="flex min-w-0 items-center gap-2.5">
                        <span className={`h-2 w-2 shrink-0 rounded-full ${t.tab === "Overdue" ? "bg-rose-500" : t.tab === "Due soon" ? "bg-orange-500" : "bg-amber-400"}`} />
                        <span className="min-w-0">
                          <span className="block truncate text-xs font-semibold text-fg">{t.title}</span>
                          <span className="block truncate text-[11px] text-fg-subtle">{t.details} • Due {t.due}</span>
                        </span>
                      </span>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold ${t.tab === "Overdue" ? "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300" : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"}`}>{t.tab}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
    ),
    recent_joiners: (
          <Panel span="col-span-12 lg:col-span-6" title={<span className="flex items-center gap-2"><UserPlus size={16} className="text-emerald-500" />Recent Joiners</span>}
            link={{ to: "/employees", label: "View Employees" }}>
            {loading ? <Loading rows={5} /> : joiners.length === 0 ? (
              <div className="flex flex-1 items-center justify-center p-4"><EmptyState icon={UserPlus} title="No recent joiners" className="py-6" /></div>
            ) : (
              <div className="flex-1 overflow-x-auto p-2">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/50 text-[10px] font-semibold uppercase text-fg-subtle">
                    <tr>
                      <th className="rounded-l-lg px-3 py-2.5">Employee</th>
                      <th className="px-3 py-2.5">Department</th>
                      <th className="px-3 py-2.5">Designation</th>
                      <th className="rounded-r-lg px-3 py-2.5">DOJ</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/40">
                    {joiners.map((j, i) => (
                      <tr key={i} className="transition-colors hover:bg-muted/30">
                        <td className="flex items-center gap-2 px-3 py-2.5 font-semibold text-fg"><Avatar name={j.name} size="sm" />{j.name}</td>
                        <td className="px-3 py-2.5 text-fg-muted">{j.department}</td>
                        <td className="px-3 py-2.5 text-fg-muted">{j.designation || "—"}</td>
                        <td className="px-3 py-2.5 font-medium text-fg">{j.hire_date ? format(new Date(j.hire_date), "d MMM yyyy") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
    ),
    quick_links: (
          <Panel span="col-span-12" title="Quick Links" badge={<span className="text-xs text-fg-subtle">Instant navigation</span>}>
            <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4 lg:grid-cols-8">
              {[
                { label: "Employees", icon: Users, to: "/employees" },
                { label: "Attendance", icon: Clock, to: "/attendance" },
                { label: "Leave", icon: Umbrella, to: "/leave" },
                { label: "Corrections", icon: TimerReset, to: "/corrections" },
                { label: "Reports", icon: BarChart3, to: "/reports" },
                { label: "Policies", icon: ShieldCheck, to: "/policy" },
                { label: "Organization", icon: Building2, to: "/organization" },
                { label: "My Profile", icon: UserCircle, to: "/profile" },
              ].map((ql) => (
                <Link key={ql.label} to={ql.to}
                  className="group flex cursor-pointer flex-col items-center justify-center rounded-xl border border-line bg-surface p-3 text-center transition-all hover:border-brand-500 hover:bg-brand-500/5">
                  <ql.icon size={20} className="text-fg-subtle transition-colors group-hover:text-brand-600 dark:group-hover:text-brand-400" />
                  <span className="mt-2 text-xs font-medium text-fg group-hover:text-brand-600 dark:group-hover:text-brand-400">{ql.label}</span>
                </Link>
              ))}
            </div>
          </Panel>
    ),
  };

  return (
    <div id="hrms-dashboard-root" className="space-y-6">
      {/* ─── Filters ─── */}
      <div className="flex flex-wrap items-center justify-end gap-2.5">
        {companies.length > 1 && (
          <select
            id="company-selector-dropdown"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            aria-label="Company"
            className="h-9 cursor-pointer rounded-lg border border-line bg-surface px-3 py-1.5 pr-8 text-xs font-medium text-fg shadow-xs outline-none transition-colors hover:border-line-strong"
          >
            <option value="">All companies</option>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <span className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg shadow-xs">
          <Calendar size={13} className="text-brand-500" />
          Today, {format(new Date(), "d MMM yyyy")}
        </span>
        <button onClick={() => setCustomizing(true)} disabled={!layout.data} className="btn-secondary btn-sm">
          <LayoutGrid size={14} /> Customize
        </button>
      </div>
      {layout.data && (
        <OverviewCustomizer open={customizing} onClose={() => setCustomizing(false)} layout={layout.data} />
      )}

      {hr.isError && (
        <Notice title="Live data is unavailable" action={<button onClick={() => hr.refetch()} className="btn-secondary btn-sm shrink-0">Retry</button>}>
          The figures below aren’t current. {errorMessage(hr.error)}
        </Notice>
      )}

      <div className="grid grid-cols-12 gap-5">
        {order.map((id) => (cards[id] ? <Fragment key={id}>{cards[id]}</Fragment> : null))}
      </div>

      <p className="flex items-center gap-1.5 text-[11px] text-fg-subtle">
        <BookOpen size={12} /> Figures cover everyone your role can see{company ? " in the selected company" : ""}.
      </p>
    </div>
  );
}

/** Show, hide and reorder the overview's cards; saved to the person's account. */
function OverviewCustomizer({ open, onClose, layout }: { open: boolean; onClose: () => void; layout: DashboardLayout }) {
  const qc = useQueryClient();
  const toast = useToast();
  const shown = layout.widgets.map((w) => w.widget);
  const initial = [...shown, ...layout.catalog.map((c) => c.id).filter((id) => !shown.includes(id))];
  const [draft, setDraft] = useState<{ order: string[]; visible: Set<string> } | null>(null);
  const current = draft ?? { order: initial, visible: new Set(shown) };
  const info = new Map(layout.catalog.map((c) => [c.id, c]));
  const done = (saved: DashboardLayout, message: string) => {
    qc.setQueryData(["dash-layout", "overview"], saved);
    setDraft(null);
    onClose();
    toast.success(message);
  };
  const save = useMutation({
    mutationFn: () => dashboardApi.saveLayout(
      current.order.filter((id) => current.visible.has(id)).map((id) => ({ widget: id, size: "full" as const })), "overview"),
    onSuccess: (saved) => done(saved, "Overview saved"),
    onError: (e) => toast.error("Couldn’t save your overview", errorMessage(e)),
  });
  const reset = useMutation({
    mutationFn: () => dashboardApi.resetLayout("overview"),
    onSuccess: (saved) => done(saved, "Overview reset to default"),
    onError: (e) => toast.error("Couldn’t reset your overview", errorMessage(e)),
  });
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = current.order.indexOf(String(active.id));
    const to = current.order.indexOf(String(over.id));
    if (from >= 0 && to >= 0) setDraft({ ...current, order: arrayMove(current.order, from, to) });
  };
  const title = (id: string | number) => info.get(String(id))?.title ?? "";
  const at = (id: string | number) => current.order.indexOf(String(id)) + 1;
  const toggle = (id: string) => {
    const visible = new Set(current.visible);
    if (visible.has(id)) visible.delete(id); else visible.add(id);
    setDraft({ ...current, visible });
  };
  return (
    <Sheet open={open} onClose={() => { setDraft(null); onClose(); }} title="Customize overview"
      description="Tick the cards you want, and drag them into the order you want."
      footer={<>
        {!layout.is_default && <button className="btn-secondary btn-sm mr-auto" onClick={() => reset.mutate()} disabled={reset.isPending}>Reset to default</button>}
        <button className="btn-secondary btn-sm" onClick={() => { setDraft(null); onClose(); }}>Cancel</button>
        <button className="btn-primary btn-sm" onClick={() => save.mutate()} disabled={save.isPending || current.visible.size === 0}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </>}>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
        accessibility={{
          screenReaderInstructions: { draggable: "Press Space to pick up a card, the arrow keys to move it, Space to drop it, or Escape to cancel." },
          announcements: {
            onDragStart: ({ active }) => `Picked up ${title(active.id)}, position ${at(active.id)} of ${current.order.length}.`,
            onDragOver: ({ active, over }) => (over ? `${title(active.id)} would move to position ${at(over.id)}.` : ""),
            onDragEnd: ({ active, over }) => (over ? `${title(active.id)} moved to position ${at(over.id)}.` : `${title(active.id)} dropped.`),
            onDragCancel: ({ active }) => `Moving ${title(active.id)} cancelled.`,
          },
        }}
      >
        <SortableContext items={current.order} strategy={verticalListSortingStrategy}>
          <ul className="space-y-2">
            {current.order.map((id) => {
              const card = info.get(id);
              if (!card) return null;
              return (
                <SortableRow key={id} id={id} title={card.title}>
                  <input type="checkbox" checked={current.visible.has(id)} onChange={() => toggle(id)} aria-label={`Show ${card.title}`} className="h-4 w-4" />
                  <div className="min-w-0 flex-1">
                    <p className={`text-[13px] font-medium ${current.visible.has(id) ? "text-fg" : "text-fg-subtle"}`}>{card.title}</p>
                    <p className="truncate text-xs text-fg-subtle">{card.description}</p>
                  </div>
                </SortableRow>
              );
            })}
          </ul>
        </SortableContext>
      </DndContext>
    </Sheet>
  );
}

/** One draggable row in the overview customizer: drag it by the row, or by the grip with the keyboard. */
function SortableRow({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  const { setNodeRef, setActivatorNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({ id });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      {...listeners}
      className={`relative flex cursor-grab items-center gap-3 rounded-xl border px-3 py-2 select-none ${
        isDragging ? "z-10 cursor-grabbing border-brand-500 bg-panel shadow-pop" : "border-line bg-panel hover:border-line-strong"
      }`}
    >
      <span
        ref={setActivatorNodeRef}
        {...attributes}
        aria-label={`Reorder ${title}`}
        className="-ml-1 grid h-7 w-5 shrink-0 place-items-center rounded text-fg-subtle focus-visible:ring-2 focus-visible:ring-brand-500"
      >
        <GripVertical size={14} aria-hidden />
      </span>
      {children}
    </li>
  );
}

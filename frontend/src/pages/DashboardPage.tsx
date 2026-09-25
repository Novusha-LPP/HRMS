import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Users, UserCheck, Umbrella, Inbox, ChevronRight, Cake, Award, UserPlus, CheckCheck,
  BarChart3, FilePenLine, CalendarX2, Timer, CalendarCheck, ArrowUpRight,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { dashboardApi } from "../api/dashboard";
import { leaveApi } from "../api/leave";
import type { LeaveApplication, LeaveBalance } from "../api/leave";
import { PunchClock } from "../components/attendance/PunchClock";
import { OnboardingChecklist } from "../components/onboarding/OnboardingChecklist";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { AreaChart, BarList, Donut, Legend, CHART } from "../components/ui/Charts";
import { Avatar } from "../components/ui/Avatar";
import { StatusBadge, TONE_CLASS } from "../components/ui/StatusBadge";
import { EmptyState, Notice, SampleTag, Skeleton } from "../components/ui/Feedback";
import {
  ACTION_ITEMS, ATTENDANCE_TREND, DEMO_EMPLOYEES, DEPT_HEADCOUNT, LEAVE_BY_TYPE, TODAY_EVENTS,
} from "../lib/demo";

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
      The API isn’t responding, so figures below are sample data. Start the backend and run migrations (see RUNBOOK.md).
    </Notice>
  );
}

/* ─────────────────────────── HR / Admin ─────────────────────────── */
function HRDashboard() {
  const { data, isPending: isLoading, isError, refetch } = useQuery({ queryKey: ["dash-hr"], queryFn: () => dashboardApi.hr() });
  const { data: apps } = useQuery<LeaveApplication[]>({
    queryKey: ["leave-applications"],
    queryFn: () => leaveApi.listApplications(),
  });

  const live = !!data && !isError;
  const hc = (data?.headcount as Dict) ?? {};
  const today = (data?.today as Dict) ?? {};
  const month = (data?.month as Dict) ?? {};
  const actions = (data?.actions as Dict) ?? {};

  const total = live ? num(hc.total) : 148;
  const present = live ? num(today.present) : 140;
  const absent = live ? num(today.absent) : 3;
  const onLeave = live ? num(today.on_leave) : 5;
  const late = live ? num(today.late) : 5;
  const newHires = live ? num(month.new_hires) : 6;
  const pending = live ? num(actions.pending_approvals) : 10;
  const presentPct = total > 0 ? Math.round((present / total) * 100) : 0;

  const leaveLive = !!apps?.length;
  const leaveStatus = leaveLive
    ? {
        pending: apps.filter((a) => a.status.includes("PENDING")).length,
        approved: apps.filter((a) => a.status === "APPROVED").length,
        rejected: apps.filter((a) => a.status === "REJECTED").length,
      }
    : { pending: 7, approved: 22, rejected: 3 };
  const leaveTypes = leaveLive
    ? Object.values(
        apps.reduce<Record<string, { label: string; value: number; color: string }>>((acc, a) => {
          acc[a.leave_type_name] ??= { label: a.leave_type_name, value: 0, color: a.leave_type_color };
          acc[a.leave_type_name].value += a.days_requested;
          return acc;
        }, {}),
      )
    : LEAVE_BY_TYPE;
  const leaveTotal = leaveTypes.reduce((s, t) => s + t.value, 0) || 1;

  const recent = [...DEMO_EMPLOYEES].sort((a, b) => b.hireDate.localeCompare(a.hireDate)).slice(0, 5);

  return (
    <div className="space-y-6">
      {isError && <ApiNotice onRetry={() => refetch()} />}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Headcount" icon={Users} loading={isLoading} value={total} delta={newHires} hint="joined this month"
          spark={[132, 135, 134, 138, 141, 140, 143, 145, 148]} />
        <StatCard label="Present today" icon={UserCheck} loading={isLoading} value={present} hint={`${presentPct}% of workforce`}
          spark={ATTENDANCE_TREND.map((d) => d.present)} />
        <StatCard label="On leave today" icon={Umbrella} loading={isLoading} value={onLeave} hint={`${absent} unplanned absences`} />
        <StatCard label="Pending approvals" icon={Inbox} loading={isLoading} value={pending} hint="leave & corrections" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <div className="card-header">
            <div>
              <h3 className="card-title">Attendance trend</h3>
              <p className="card-desc">Daily attendance rate · last 12 working days</p>
            </div>
            <div className="flex items-center gap-2">
              <Link to="/daily-analysis" className="btn-ghost btn-sm text-xs gap-1">
                <span>Daily analysis</span>
                <ArrowUpRight size={13} />
              </Link>
              <SampleTag />
            </div>
          </div>
          <div className="px-5 pb-5">
            <AreaChart
              min={84}
              max={100}
              unit="%"
              data={ATTENDANCE_TREND.map((d) => ({
                label: d.label,
                value: d.value,
                detail: (
                  <div className="grid grid-cols-3 gap-2 tabular-nums">
                    <span><b className="font-medium text-success">{d.present}</b> in</span>
                    <span><b className="font-medium text-warning">{d.late}</b> late</span>
                    <span><b className="font-medium text-danger">{d.absent}</b> out</span>
                  </div>
                ),
              }))}
            />
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div>
              <h3 className="card-title">Today</h3>
              <p className="card-desc">{format(new Date(), "EEEE, d MMM")}</p>
            </div>
            <Link to="/attendance" className="link text-xs">Details</Link>
          </div>
          <div className="flex flex-col items-center gap-6 px-5 pb-5 sm:flex-row lg:flex-col xl:flex-row">
            {isLoading ? (
              <Skeleton className="h-[152px] w-[152px] rounded-full" />
            ) : (
              <Donut
                segments={[
                  { label: "Present", value: Math.max(present - late, 0), color: CHART.present },
                  { label: "Late", value: late, color: CHART.late },
                  { label: "Absent", value: absent, color: CHART.absent },
                  { label: "On leave", value: onLeave, color: CHART.leave },
                ]}
              >
                <span className="text-2xl font-semibold tabular-nums text-fg">{presentPct}%</span>
                <span className="text-[11px] text-fg-subtle">present</span>
              </Donut>
            )}
            <div className="w-full flex-1">
              <Legend
                items={[
                  { label: "On time", color: CHART.present, value: isLoading ? "–" : Math.max(present - late, 0) },
                  { label: "Late", color: CHART.late, value: isLoading ? "–" : late },
                  { label: "Absent", color: CHART.absent, value: isLoading ? "–" : absent },
                  { label: "On leave", color: CHART.leave, value: isLoading ? "–" : onLeave },
                ]}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Headcount by department</h3>
            <SampleTag />
          </div>
          <div className="px-5 pb-5"><BarList items={DEPT_HEADCOUNT} /></div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Action centre</h3>
            <SampleTag />
          </div>
          <ul className="px-2 pb-2">
            {ACTION_ITEMS.map((a) => (
              <li key={a.label}>
                <Link to={a.to} className="group flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] transition-colors hover:bg-muted">
                  <span className="flex-1 text-fg-muted group-hover:text-fg">{a.label}</span>
                  <span className={`${TONE_CLASS[a.tone]} tabular-nums`}>{a.count}</span>
                  <ChevronRight size={14} className="text-fg-subtle transition-transform group-hover:translate-x-0.5" />
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Today at SFPL</h3>
            <SampleTag />
          </div>
          <ul className="space-y-1 px-2 pb-2">
            {TODAY_EVENTS.map((e) => {
              const Icon = e.kind === "birthday" ? Cake : e.kind === "anniversary" ? Award : UserPlus;
              return (
                <li key={e.name} className="flex items-center gap-3 rounded-lg px-3 py-2">
                  <Avatar name={e.name} size="md" />
                  <div className="min-w-0 flex-1 leading-tight">
                    <p className="truncate text-[13px] font-medium text-fg">{e.name}</p>
                    <p className="truncate text-xs text-fg-subtle">{e.detail}</p>
                  </div>
                  <span className="grid h-7 w-7 place-items-center rounded-lg bg-muted text-fg-subtle"><Icon size={14} /></span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card overflow-hidden lg:col-span-2">
          <div className="card-header">
            <div className="flex items-center gap-2">
              <h3 className="card-title">Recent joiners</h3>
              <SampleTag />
            </div>
            <Link to="/employees" className="link text-xs">View all</Link>
          </div>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th>Employee</th><th>Department</th><th className="hidden md:table-cell">Role</th><th>Joined</th><th>Status</th></tr>
              </thead>
              <tbody>
                {recent.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <div className="flex items-center gap-3">
                        <Avatar name={e.name} size="sm" />
                        <div className="min-w-0 leading-tight">
                          <p className="truncate font-medium text-fg">{e.name}</p>
                          <p className="truncate text-xs text-fg-subtle">{e.employeeNumber}</p>
                        </div>
                      </div>
                    </td>
                    <td>{e.department}</td>
                    <td className="hidden md:table-cell">{e.designation}</td>
                    <td className="whitespace-nowrap tabular-nums">{format(new Date(e.hireDate), "d MMM yyyy")}</td>
                    <td><StatusBadge status={e.state} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Leave overview</h3>
            {leaveLive ? <Link to="/leave" className="link text-xs">Open</Link> : <SampleTag />}
          </div>
          <div className="px-5 pb-5">
            <div className="grid grid-cols-3 divide-x divide-line rounded-lg border border-line">
              {[
                { label: "Pending", value: leaveStatus.pending, cls: "text-warning" },
                { label: "Approved", value: leaveStatus.approved, cls: "text-success" },
                { label: "Rejected", value: leaveStatus.rejected, cls: "text-danger" },
              ].map((s) => (
                <div key={s.label} className="px-3 py-3 text-center">
                  <p className={`text-xl font-semibold tabular-nums ${s.cls}`}>{s.value}</p>
                  <p className="text-[11px] text-fg-subtle">{s.label}</p>
                </div>
              ))}
            </div>
            <p className="eyebrow mb-2.5 mt-5">Days by leave type</p>
            <div className="flex h-2 overflow-hidden rounded-full bg-muted">
              {leaveTypes.map((t) => (
                <div key={t.label} style={{ width: `${(t.value / leaveTotal) * 100}%`, background: t.color }} className="h-full first:rounded-l-full last:rounded-r-full" />
              ))}
            </div>
            <div className="mt-4"><Legend items={leaveTypes.map((t) => ({ label: t.label, color: t.color, value: `${t.value}d` }))} /></div>
          </div>
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
  const approvals = (data?.pending_approvals as Dict[]) ?? [];

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
        <div className="card lg:col-span-2">
          <div className="card-header">
            <div>
              <h3 className="card-title">Waiting on you</h3>
              <p className="card-desc">Requests from your team that need a decision</p>
            </div>
            <Link to="/leave?tab=approvals" className="btn-secondary btn-sm">Review all</Link>
          </div>
          {approvals.length === 0 ? (
            <EmptyState icon={CheckCheck} title="No pending approvals" description="New requests from your team will appear here." />
          ) : (
            <ul className="divide-y divide-line border-t border-line">
              {approvals.map((pa, i) => (
                <li key={i} className="flex items-center justify-between gap-4 px-5 py-3">
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-fg">{String(pa.type ?? "Request")}</p>
                    <p className="text-xs text-fg-subtle">Effective {String(pa.effective_date ?? "—")}</p>
                  </div>
                  <StatusBadge status="PENDING" />
                </li>
              ))}
            </ul>
          )}
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
  const first = user.name.split(" ")[0];
  const isHR = user.role === "HR" || user.role === "SUPER_ADMIN";

  const actions = isHR ? (
    <>
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
        title={`${greeting()}, ${first}`}
        description={isHR ? `Here’s what’s happening across ${user.tenantName} today.` : "Here’s your day at a glance."}
        actions={actions}
      />
      {isHR && <HRDashboard />}
      {user.role === "MANAGER" && user.employmentId && <ManagerDashboard employmentId={user.employmentId} />}
      {user.role === "EMPLOYEE" && user.employmentId && <EmployeeDashboard employmentId={user.employmentId} />}
    </>
  );
}

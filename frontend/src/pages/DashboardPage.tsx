import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Users, UserCheck, CalendarCheck, CalendarX2, Umbrella,
  CheckCheck, BarChart3, FilePenLine, Timer, LayoutGrid, LayoutDashboard,
} from "../components/icons/ThemeIcons";
import { dashboardApi } from "../api/dashboard";
import { leaveApi } from "../api/leave";
import type { LeaveBalance } from "../api/leave";
import { useAuth } from "../context/AuthContext";
import { PendingApprovalsQueue } from "../components/dashboard/PendingApprovalsQueue";
import type { PendingRequestItem } from "../components/dashboard/PendingApprovalsQueue";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { PunchClock } from "../components/attendance/PunchClock";
import { OnboardingChecklist } from "../components/onboarding/OnboardingChecklist";

import { HRMSDashboardView } from "../components/dashboard/HRMSDashboardView";
import { CustomizableDashboard } from "../components/dashboard/CustomizableDashboard";
import { Segmented } from "../components/ui/Tabs";
import { usePreferences, useUpdatePreferences } from "../lib/preferences";
import type { DashboardStyle } from "../api/preferences";

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


/* ─────────────────────────── HR / Admin ─────────────────────────── */
/**
 * HR and admins choose their own dashboard (saved to their account, independent of the
 * colour theme): the customisable widget grid, or the fixed HRMS overview.
 */
function HRDashboard({ style }: { style: DashboardStyle }) {
  return style === "overview" ? <HRMSDashboardView /> : <CustomizableDashboard />;
}

function DashboardStyleSwitch({ style }: { style: DashboardStyle }) {
  const update = useUpdatePreferences();
  return (
    <Segmented<DashboardStyle>
      value={style}
      onChange={(next) => update.mutate({ dashboard_style: next })}
      items={[
        { value: "widgets", label: "Widgets", icon: LayoutGrid },
        { value: "overview", label: "Overview", icon: LayoutDashboard },
      ]}
    />
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
  const prefs = usePreferences();
  if (!user) return null;
  // While the saved choice loads, show neither dashboard; if it can't load, fall back to widgets.
  const style: DashboardStyle | undefined = prefs.isError ? "widgets" : prefs.data?.dashboard_style;
  // Admin-only accounts have no person record, so their "name" is just their email.
  const first = user.name.includes("@") ? "" : user.name.split(" ")[0];
  const isHR = user.role === "HR" || user.role === "SUPER_ADMIN";
  const showsHrDashboard = isHR || !user.employmentId;

  const actions = isHR ? (
    <>
      {style && <DashboardStyleSwitch style={style} />}
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
      {showsHrDashboard && (style
        ? <HRDashboard style={style} />
        : <Skeleton className="h-64 w-full rounded-xl" />)}
      {user.role === "MANAGER" && user.employmentId && <ManagerDashboard employmentId={user.employmentId} />}
      {user.role === "EMPLOYEE" && user.employmentId && <EmployeeDashboard employmentId={user.employmentId} />}
    </>
  );
}

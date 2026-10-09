import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Users, UserCheck, CalendarX2, Umbrella,
  CheckCheck, BarChart3, FilePenLine, LayoutGrid, LayoutDashboard,
} from "../components/icons/ThemeIcons";
import { dashboardApi } from "../api/dashboard";
import { useAuth } from "../context/AuthContext";
import { PendingApprovalsQueue } from "../components/dashboard/PendingApprovalsQueue";
import type { PendingRequestItem } from "../components/dashboard/PendingApprovalsQueue";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { Avatar } from "../components/ui/Avatar";
import { StatusBadge } from "../components/ui/StatusBadge";
import {
  KycTodo, LeaveBalanceCard, MonthStats, MyRequestsCard, UpcomingHolidaysCard, WeekStrip,
} from "../components/dashboard/EmployeeHome";
import { memberState } from "../components/team/teamStatus";
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

/* ─────────────────────────── Your own cards ─────────────────────────── */
function useEmployeeDashboard(employmentId: string) {
  return useQuery({
    queryKey: ["dash-emp", employmentId],
    queryFn: () => dashboardApi.employee(employmentId),
  });
}

/** The personal half of the home page, shared by employees and managers. */
function PersonalSections({ employmentId }: { employmentId: string }) {
  const { data, isPending } = useEmployeeDashboard(employmentId);
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-3">
        <LeaveBalanceCard employmentId={employmentId} />
        <MyRequestsCard employmentId={employmentId} />
        <UpcomingHolidaysCard holidays={data?.upcoming_holidays} loading={isPending} />
      </div>
      <OnboardingChecklist employmentId={employmentId} hideWhenEmpty />
    </>
  );
}

/* ─────────────────────────── Manager ─────────────────────────── */
function TeamTodayCard() {
  const { data, isPending } = useQuery({ queryKey: ["dash-team"], queryFn: () => dashboardApi.team(), refetchInterval: 60_000 });
  const rows = (data?.members ?? []).map((m) => ({ m, s: memberState(m) }));
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3 className="card-title">Team today</h3>
          <p className="card-desc">Who’s in, who’s late and who’s away</p>
        </div>
        <Link to="/team" className="link text-xs">Open my team</Link>
      </div>
      {isPending ? (
        <div className="space-y-3 px-5 pb-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>
      ) : !rows.length ? (
        <EmptyState icon={Users} title="No direct reports yet" description="People appear here once HR sets you as their line manager." className="py-10" />
      ) : (
        <ul className="divide-y divide-line border-t border-line">
          {rows.slice(0, 6).map(({ m, s }) => (
            <li key={m.employment_id} className="flex items-center gap-3 px-5 py-2.5 text-[13px]">
              <Avatar name={m.name} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-fg">{m.name}</span>
                <span className="block truncate text-xs text-fg-subtle">{s.firstIn ? `In ${s.firstIn}${s.lastOut ? ` · Out ${s.lastOut}` : ""}` : m.designation ?? m.employee_number}</span>
              </span>
              {s.late && <span className="badge badge-warning">Late</span>}
              <StatusBadge tone={s.tone} label={s.label} />
            </li>
          ))}
          {rows.length > 6 && (
            <li><Link to="/team" className="block px-5 py-2.5 text-center text-xs font-medium text-accent hover:bg-muted/50">See all {rows.length}</Link></li>
          )}
        </ul>
      )}
    </div>
  );
}

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
      <KycTodo />
      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <StatCard label="Team size" icon={Users} loading={isLoading} value={num(data?.team_size)} hint={<Link to="/team" className="link">View team</Link>} />
        <StatCard label="Present today" icon={UserCheck} iconTone="green" loading={isLoading} value={num(today.present)} />
        <StatCard label="Absent today" icon={CalendarX2} iconTone="red" loading={isLoading} value={num(today.absent)} />
        <StatCard label="On leave" icon={Umbrella} loading={isLoading} value={num(today.on_leave)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <PendingApprovalsQueue
            items={approvals}
            isLoading={isLoading}
            queryKeyToRefresh={[["dash-mgr", employmentId], ["dash-team"], ["leave-applications"], ["corrections"]]}
            emptyHint="New requests from your team will appear here."
          />
          <TeamTodayCard />
          <WeekStrip employmentId={employmentId} />
        </div>
        <PunchClock employmentId={employmentId} />
      </div>
      <PersonalSections employmentId={employmentId} />
    </div>
  );
}

/* ─────────────────────────── Employee ─────────────────────────── */
function EmployeeDashboard({ employmentId }: { employmentId: string }) {
  const { data, isPending: isLoading, isError, refetch } = useEmployeeDashboard(employmentId);

  return (
    <div className="space-y-6">
      {isError && <ApiNotice onRetry={() => refetch()} />}
      <KycTodo />
      <div className="grid gap-4 lg:grid-cols-3">
        <PunchClock employmentId={employmentId} />
        <div className="space-y-4 lg:col-span-2">
          <MonthStats data={data} loading={isLoading} />
          <WeekStrip employmentId={employmentId} />
        </div>
      </div>
      <PersonalSections employmentId={employmentId} />
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
      {user.role === "MANAGER" && <Link to="/team" className="btn-secondary"><Users size={15} /> My team</Link>}
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

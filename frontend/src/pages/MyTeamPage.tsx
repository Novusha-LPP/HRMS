import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Search } from "lucide-react";
import {
  CalendarCheck, CalendarClock, ChevronRight, NavigationUsers as Users, Timer, Umbrella, UserCheck, Plane,
} from "../components/icons/ThemeIcons";
import { dashboardApi } from "../api/dashboard";
import type { TeamLeave, TeamMember } from "../api/dashboard";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Avatar } from "../components/ui/Avatar";
import { EmptyState, NoEmployeeRecord, Notice, Skeleton } from "../components/ui/Feedback";
import { PendingApprovalsQueue } from "../components/dashboard/PendingApprovalsQueue";
import type { PendingRequestItem } from "../components/dashboard/PendingApprovalsQueue";
import { fmtMins } from "../components/attendance/registerModel";
import { atWork, memberState, type MemberState, type TeamBucket } from "../components/team/teamStatus";

type Filter = "all" | "at_work" | "late" | TeamBucket;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "Everyone" },
  { value: "at_work", label: "At work" },
  { value: "late", label: "Late" },
  { value: "not_in", label: "Not checked in" },
  { value: "leave", label: "On leave" },
  { value: "off", label: "Day off" },
];

function matches(filter: Filter, s: MemberState) {
  if (filter === "all") return true;
  if (filter === "at_work") return atWork(s);
  if (filter === "late") return s.late;
  return s.bucket === filter;
}

export function MyTeamPage() {
  const { user } = useAuth();
  if (!user) return null;
  if (!user.employmentId) {
    return (
      <>
        <PageHeader title="My team" description="The people who report to you." />
        <NoEmployeeRecord feature="team of direct reports" />
      </>
    );
  }
  return <TeamView employmentId={user.employmentId} />;
}

function TeamView({ employmentId }: { employmentId: string }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const team = useQuery({ queryKey: ["dash-team"], queryFn: () => dashboardApi.team(), refetchInterval: 60_000 });
  const mgr = useQuery({ queryKey: ["dash-mgr", employmentId], queryFn: () => dashboardApi.manager(employmentId) });
  const approvals = (mgr.data?.pending_approvals as PendingRequestItem[] | undefined) ?? [];

  const rows = useMemo(
    () => (team.data?.members ?? []).map((m) => ({ m, s: memberState(m) })),
    [team.data],
  );
  const count = (f: Filter) => rows.filter((r) => matches(f, r.s)).length;
  const q = search.trim().toLowerCase();
  const visible = rows.filter((r) => matches(filter, r.s)
    && (!q || [r.m.name, r.m.employee_number, r.m.designation ?? ""].some((v) => v.toLowerCase().includes(q))));
  const size = rows.length;
  const loading = team.isPending;

  return (
    <>
      <PageHeader
        title="My team"
        description={loading ? "Your direct reports today." : `${size} direct report${size === 1 ? "" : "s"} · ${format(new Date(), "EEEE, d MMMM")}`}
        actions={
          <>
            <Link to="/attendance/register" className="btn-secondary"><CalendarCheck size={15} /> Attendance register</Link>
            <Link to="/approvals" className="btn-secondary">Approvals</Link>
          </>
        }
      />

      {team.isError && (
        <div className="mb-6">
          <Notice title="Your team couldn’t be loaded" action={<button className="btn-secondary btn-sm shrink-0" onClick={() => team.refetch()}>Retry</button>}>
            The figures below may be out of date.
          </Notice>
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <StatCard label="At work" icon={UserCheck} iconTone="green" loading={loading} value={count("at_work")} hint={`of ${size} today`} />
        <StatCard label="Late today" icon={Timer} iconTone="orange" loading={loading} value={count("late")} hint="after grace time" />
        <StatCard label="Not checked in" icon={CalendarClock} iconTone="red" loading={loading} value={count("not_in")} hint="on a working day" />
        <StatCard label="On leave" icon={Umbrella} iconTone="blue" loading={loading} value={count("leave")} hint={`${count("off")} on a day off`} />
      </div>

      <div className="grid items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="card min-w-0">
          <div className="flex flex-col gap-3 border-b border-line px-5 py-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="no-scrollbar -mx-1 overflow-x-auto px-1">
              <div className="seg" role="radiogroup" aria-label="Filter team">
                {FILTERS.map((f) => (
                  <button key={f.value} role="radio" aria-checked={filter === f.value} data-active={filter === f.value} onClick={() => setFilter(f.value)} className="seg-item whitespace-nowrap">
                    {f.label}
                    {!loading && <span className="tabular-nums text-fg-subtle">{count(f.value)}</span>}
                  </button>
                ))}
              </div>
            </div>
            <label className="relative block xl:w-60 xl:shrink-0">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
              <input className="input pl-8" placeholder="Search name, code, role" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search team" />
            </label>
          </div>

          {loading ? (
            <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</div>
          ) : !size ? (
            <EmptyState
              icon={Users}
              title="No direct reports yet"
              description="People appear here once HR sets you as their line manager."
            />
          ) : !visible.length ? (
            <EmptyState icon={Search} title="No one matches" description="Try another filter or search." className="py-10" />
          ) : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Member</th>
                    <th>Today</th>
                    <th className="hidden md:table-cell">In</th>
                    <th className="hidden md:table-cell">Out</th>
                    <th className="hidden sm:table-cell">Worked</th>
                    <th className="hidden lg:table-cell" title="Present · late · absent days this month">{team.data?.month ?? "This month"}</th>
                    <th aria-label="Open" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map(({ m, s }) => <MemberRow key={m.employment_id} m={m} s={s} />)}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <div className="grid items-start gap-6 lg:grid-cols-2 2xl:grid-cols-1">
          <PendingApprovalsQueue
            items={approvals}
            isLoading={mgr.isPending}
            queryKeyToRefresh={[["dash-mgr", employmentId], ["dash-team"], ["leave-applications"], ["corrections"]]}
            emptyHint="New requests from your team will appear here."
          />
          <TeamLeaveCard leave={team.data?.upcoming_leave} loading={loading} />
        </div>
      </div>
    </>
  );
}

function MemberRow({ m, s }: { m: TeamMember; s: MemberState }) {
  const t = m.today;
  return (
    <tr>
      <td>
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={m.name} size="md" />
          <div className="min-w-0">
            <p className="truncate font-medium text-fg">{m.name}</p>
            <p className="truncate text-xs text-fg-subtle">{[m.employee_number, m.designation].filter(Boolean).join(" · ")}</p>
          </div>
        </div>
      </td>
      <td>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge tone={s.tone} label={s.label} />
          {s.late && t && <span className="badge badge-warning">Late {fmtMins(t.late_by_minutes, "")}</span>}
        </div>
      </td>
      <td className="hidden whitespace-nowrap tabular-nums md:table-cell">{s.firstIn ?? "—"}</td>
      <td className="hidden whitespace-nowrap tabular-nums md:table-cell">{s.lastOut ?? (s.bucket === "in" ? <span className="text-success">Working</span> : "—")}</td>
      <td className="hidden whitespace-nowrap tabular-nums sm:table-cell">{t ? fmtMins(t.effective_minutes) : "—"}</td>
      <td className="hidden lg:table-cell">
        <span className="inline-flex items-center gap-2 whitespace-nowrap tabular-nums text-xs">
          <span title="Days present"><b className="font-semibold text-success">{m.month.present}</b> P</span>
          <span title="Late arrivals"><b className="font-semibold text-warning">{m.month.late}</b> L</span>
          <span title="Days absent"><b className="font-semibold text-danger">{m.month.absent}</b> A</span>
        </span>
      </td>
      <td className="text-right">
        <Link
          to={`/attendance/register?employee=${encodeURIComponent(m.employment_id)}`}
          className="btn-icon"
          title={`Open ${m.name}’s attendance`}
          aria-label={`Open ${m.name}’s attendance`}
        >
          <ChevronRight size={15} />
        </Link>
      </td>
    </tr>
  );
}

function TeamLeaveCard({ leave, loading }: { leave?: TeamLeave[]; loading: boolean }) {
  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h3 className="card-title">Team leave</h3>
          <p className="card-desc">Approved and pending, next 30 days</p>
        </div>
      </div>
      {loading ? (
        <div className="space-y-3 px-5 pb-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
      ) : !leave?.length ? (
        <EmptyState icon={Plane} title="No leave coming up" description="Nobody on your team has leave booked in the next 30 days." className="py-8" />
      ) : (
        <ul className="divide-y divide-line border-t border-line">
          {leave.map((l) => (
            <li key={l.id} className="flex items-center gap-3 px-5 py-2.5">
              <Avatar name={l.name} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-fg">{l.name}</p>
                <p className="flex items-center gap-1.5 truncate text-xs text-fg-subtle">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: l.color }} />
                  {l.leave_type} · {l.from_date === l.to_date
                    ? format(parseISO(l.from_date), "d MMM")
                    : `${format(parseISO(l.from_date), "d MMM")} – ${format(parseISO(l.to_date), "d MMM")}`} · {l.days}d
                </p>
              </div>
              <StatusBadge status={l.status} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addMonths, eachDayOfInterval, endOfMonth, format, getDay, isAfter, isSameDay, startOfMonth, subMonths,
} from "date-fns";
import {
  CalendarDays, ChevronLeft, ChevronRight, FilePenLine, List, CalendarCheck, Timer, CalendarX2, Umbrella,
  Clock3, CircleCheck, CircleX,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { timeApi } from "../api/time";
import type { AttendanceDay, PendingOvertimeItem } from "../api/time";
import { PunchClock } from "../components/attendance/PunchClock";
import { PageHeader } from "../components/ui/PageHeader";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Segmented } from "../components/ui/Tabs";
import { EmptyState, Notice, NoEmployeeRecord, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";

const DOT: Record<string, string> = {
  PRESENT: "bg-success", LATE: "bg-warning", ABSENT: "bg-danger", ON_LEAVE: "bg-info",
  HOLIDAY: "bg-plum", HALF_DAY: "bg-warning", WEEKEND: "bg-line-strong",
};

const CELL: Record<string, string> = {
  PRESENT: "bg-success/[0.07] border-success/20",
  LATE: "bg-warning/[0.08] border-warning/25",
  ABSENT: "bg-danger/[0.07] border-danger/20",
  ON_LEAVE: "bg-info/[0.07] border-info/20",
  HOLIDAY: "bg-plum/[0.07] border-plum/20",
  HALF_DAY: "bg-warning/[0.08] border-warning/25",
};

function fmtMins(m: number) {
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}h ${m % 60}m` : `${m % 60}m`;
}

export function AttendancePage() {
  const { user } = useAuth();
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const [view, setView] = useState<"calendar" | "list">("calendar");
  const from = format(month, "yyyy-MM-dd");
  const to = format(endOfMonth(month), "yyyy-MM-dd");
  const isCurrentMonth = isSameDay(month, startOfMonth(new Date()));

  const { data, isPending: isLoading, isError, refetch } = useQuery<AttendanceDay[]>({
    queryKey: ["attendance-days", user?.employmentId, from, to],
    queryFn: () => timeApi.attendanceDays(user!.employmentId!, from, to),
    enabled: !!user?.employmentId,
  });

  if (!user) return null;
  if (!user.employmentId) {
    const canReview = ["HR", "SUPER_ADMIN", "MANAGER"].includes(user.role);
    return (
      <>
        <PageHeader
          title="Attendance"
          description="Your check-ins, working hours and monthly record."
          actions={canReview ? <Link to="/daily-analysis" className="btn-secondary"><CalendarCheck size={15} /> Daily Analysis</Link> : undefined}
        />
        {canReview && <div className="mb-4"><OvertimeApprovals /></div>}
        <NoEmployeeRecord feature="attendance record" />
      </>
    );
  }

  const days = data ?? [];
  const byDate = new Map(days.map((d) => [d.work_date.slice(0, 10), d]));
  const count = (...s: string[]) => days.filter((d) => s.includes(d.status)).length;
  const worked = days.reduce((sum, d) => sum + d.effective_minutes, 0);

  const stats = [
    { label: "Present", value: count("PRESENT", "LATE"), icon: CalendarCheck, cls: "text-success" },
    { label: "Late", value: count("LATE"), icon: Timer, cls: "text-warning" },
    { label: "Absent", value: count("ABSENT"), icon: CalendarX2, cls: "text-danger" },
    { label: "On leave", value: count("ON_LEAVE"), icon: Umbrella, cls: "text-info" },
  ];

  return (
    <>
      <PageHeader
        title="Attendance"
        description="Your check-ins, working hours and monthly record."
        actions={
          <div className="flex items-center gap-2">
            {["HR", "SUPER_ADMIN", "MANAGER"].includes(user.role) && (
              <Link to="/daily-analysis" className="btn-secondary">
                <CalendarCheck size={15} /> Daily Analysis
              </Link>
            )}
            <Link to="/corrections?new=1" className="btn-secondary">
              <FilePenLine size={15} /> Request correction
            </Link>
          </div>
        }
      />

      {isError && (
        <div className="mb-4">
          <Notice title="Couldn’t load attendance" action={<button className="btn-secondary btn-sm" onClick={() => refetch()}>Retry</button>}>
            The attendance API isn’t responding.
          </Notice>
        </div>
      )}

      {["HR", "SUPER_ADMIN", "MANAGER"].includes(user.role) && (
        <div className="mb-4">
          <OvertimeApprovals />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <PunchClock employmentId={user.employmentId} />

        <div className="card lg:col-span-2">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
            <div className="flex items-center gap-1">
              <button className="btn-icon" onClick={() => setMonth((m) => subMonths(m, 1))} aria-label="Previous month"><ChevronLeft size={16} /></button>
              <h3 className="w-36 text-center text-sm font-semibold text-fg">{format(month, "MMMM yyyy")}</h3>
              <button className="btn-icon" onClick={() => setMonth((m) => addMonths(m, 1))} disabled={isCurrentMonth} aria-label="Next month"><ChevronRight size={16} /></button>
            </div>
            {!isCurrentMonth && (
              <button className="btn-ghost btn-sm" onClick={() => setMonth(startOfMonth(new Date()))}>Today</button>
            )}
            <div className="ml-auto">
              <Segmented
                value={view}
                onChange={setView}
                items={[{ value: "calendar", label: "Calendar", icon: CalendarDays }, { value: "list", label: "List", icon: List }]}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 divide-line border-b border-line sm:grid-cols-5 sm:divide-x">
            {stats.map((s) => (
              <div key={s.label} className="px-5 py-3.5">
                <p className="flex items-center gap-1.5 text-xs text-fg-subtle"><s.icon size={13} className={s.cls} />{s.label}</p>
                <p className="mt-1 text-xl font-semibold tabular-nums text-fg">{isLoading || isError ? "–" : s.value}</p>
              </div>
            ))}
            <div className="col-span-2 px-5 py-3.5 sm:col-span-1">
              <p className="text-xs text-fg-subtle">Hours worked</p>
              <p className="mt-1 text-xl font-semibold tabular-nums text-fg">{isLoading || isError ? "–" : fmtMins(worked)}</p>
            </div>
          </div>

          {isLoading ? (
            <div className="grid grid-cols-7 gap-1.5 p-5">
              {Array.from({ length: 35 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
            </div>
          ) : view === "calendar" ? (
            <MonthGrid month={month} byDate={byDate} />
          ) : days.length === 0 ? (
            <EmptyState icon={CalendarDays} title="No attendance records" description={`Nothing recorded for ${format(month, "MMMM yyyy")} yet.`} />
          ) : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead>
                  <tr><th>Date</th><th>Status</th><th>Check in</th><th>Check out</th><th className="text-right">Worked</th></tr>
                </thead>
                <tbody>
                  {days.map((d) => (
                    <tr key={d.id}>
                      <td className="whitespace-nowrap font-medium text-fg">{format(new Date(d.work_date), "EEE, d MMM")}</td>
                      <td><StatusBadge status={d.status} /></td>
                      <td className="tabular-nums">{d.first_punch_in ? format(new Date(d.first_punch_in), "hh:mm a") : "—"}</td>
                      <td className="tabular-nums">{d.last_punch_out ? format(new Date(d.last_punch_out), "hh:mm a") : "—"}</td>
                      <td className="text-right tabular-nums">{fmtMins(d.effective_minutes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function MonthGrid({ month, byDate }: { month: Date; byDate: Map<string, AttendanceDay> }) {
  const today = new Date();
  const days = eachDayOfInterval({ start: month, end: endOfMonth(month) });
  const lead = (getDay(month) + 6) % 7; // Monday-first

  return (
    <div className="p-4 sm:p-5">
      <div className="mb-2 grid grid-cols-7 gap-1.5 text-center text-[11px] font-medium text-fg-subtle">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <span key={d}>{d}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-1.5">
        {Array.from({ length: lead }).map((_, i) => <div key={`lead-${i}`} />)}
        {days.map((day) => {
          const rec = byDate.get(format(day, "yyyy-MM-dd"));
          const future = isAfter(day, today);
          const weekend = getDay(day) === 0 || getDay(day) === 6;
          const isToday = isSameDay(day, today);
          return (
            <div
              key={day.toISOString()}
              title={rec ? `${format(day, "d MMM")} · ${rec.status.replace(/_/g, " ").toLowerCase()}` : undefined}
              className={`flex h-14 flex-col justify-between rounded-lg border p-1.5 text-left sm:h-16 sm:p-2 ${
                rec ? CELL[rec.status] ?? "border-line bg-surface" : weekend ? "border-transparent bg-muted/60" : "border-line bg-surface"
              } ${future ? "opacity-40" : ""} ${isToday ? "ring-2 ring-brand-500 ring-offset-1 ring-offset-surface" : ""}`}
            >
              <span className={`text-xs font-medium tabular-nums ${isToday ? "text-accent" : "text-fg-muted"}`}>{format(day, "d")}</span>
              {rec && (
                <span className="flex items-center gap-1">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[rec.status] ?? "bg-fg-subtle"}`} />
                  <span className="hidden truncate text-[10px] tabular-nums text-fg-subtle sm:inline">
                    {rec.effective_minutes ? fmtMins(rec.effective_minutes) : rec.status.replace(/_/g, " ").toLowerCase()}
                  </span>
                </span>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-fg-subtle">
        {[["Present", "bg-success"], ["Late", "bg-warning"], ["Absent", "bg-danger"], ["On leave", "bg-info"], ["Holiday", "bg-plum"]].map(([l, c]) => (
          <span key={l} className="flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${c}`} />{l}</span>
        ))}
      </div>
    </div>
  );
}

function fmtOtMins(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? (m > 0 ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
}

/**
 * Overtime is computed by the same policy engine as everything else on this
 * page, but needs a human review before it counts as approved — this is
 * that review queue. See POST-review logic in time/router.py:review_overtime.
 */
function OvertimeApprovals() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isPending, isError } = useQuery({
    queryKey: ["pending-overtime"],
    queryFn: () => timeApi.pendingOvertime(),
  });

  const review = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "APPROVED" | "REJECTED" }) => timeApi.reviewOvertime(id, status),
    onSuccess: (_r, vars) => {
      qc.invalidateQueries({ queryKey: ["pending-overtime"] });
      toast.success(vars.status === "APPROVED" ? "Overtime approved" : "Overtime rejected");
    },
    onError: (e) => toast.error("Couldn't update overtime", errorMessage(e)),
  });

  const items = data ?? [];
  if (!isPending && !isError && items.length === 0) return null; // nothing pending — don't take up space

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3 className="card-title flex items-center gap-1.5"><Clock3 size={15} className="text-warning" /> Overtime awaiting review</h3>
          <p className="card-desc">Policy-computed overtime for people in your scope, pending approval.</p>
        </div>
      </div>
      {isPending ? (
        <div className="space-y-2 p-5 pt-0">{[0, 1].map((i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
      ) : isError ? (
        <p className="px-5 pb-5 text-sm text-danger">Couldn't load pending overtime.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Employee</th><th>Date</th><th>Worked</th><th>Overtime</th><th className="text-right">Review</th></tr></thead>
            <tbody>
              {items.map((it: PendingOvertimeItem) => (
                <tr key={it.attendance_day_id}>
                  <td className="font-medium text-fg">{it.name}<span className="ml-1.5 text-xs text-fg-subtle">{it.department ?? it.employee_number}</span></td>
                  <td className="tabular-nums">{format(new Date(it.work_date), "d MMM")}</td>
                  <td className="tabular-nums">{fmtOtMins(it.effective_minutes)}</td>
                  <td className="tabular-nums font-medium text-warning">+{fmtOtMins(it.ot_minutes)}</td>
                  <td className="text-right">
                    <span className="inline-flex items-center gap-1.5">
                      <button
                        onClick={() => review.mutate({ id: it.attendance_day_id, status: "REJECTED" })}
                        disabled={review.isPending} className="btn-icon text-danger hover:bg-danger/10" aria-label="Reject"
                      >
                        <CircleX size={16} />
                      </button>
                      <button
                        onClick={() => review.mutate({ id: it.attendance_day_id, status: "APPROVED" })}
                        disabled={review.isPending} className="btn-icon text-success hover:bg-success/10" aria-label="Approve"
                      >
                        <CircleCheck size={16} />
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

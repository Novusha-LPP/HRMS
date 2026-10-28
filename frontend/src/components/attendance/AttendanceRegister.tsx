import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { addMonths, endOfMonth, format, getDay, isSameMonth, startOfMonth, subMonths } from "date-fns";
import {
  ChevronLeft, ChevronRight, Pencil, ShieldAlert, CalendarDays, List, Clock3, CalendarPlus,
  CircleCheck, CircleX, Timer, Umbrella, Hourglass,
} from "lucide-react";
import { timeApi, type RegisterDay, type RegisterResponse } from "../../api/time";
import { useAuth } from "../../context/AuthContext";
import { StatusBadge } from "../ui/StatusBadge";
import { Segmented } from "../ui/Tabs";
import { Skeleton, Notice, EmptyState } from "../ui/Feedback";
import { Avatar } from "../ui/Avatar";
import { DayTimeline } from "./DayTimeline";
import { DayPanel } from "./DayPanel";
import { fmtMins, hasWork, punchTime, timelineRange } from "./registerModel";
import { zonedParts } from "../../lib/zonedTime";

/** "09:30" on the policy clock — compact, for calendar cells. */
const shortTime = (iso: string | null | undefined, d: RegisterDay) => (iso ? zonedParts(iso, d.timezone).time : "");

type Filter = "ALL" | "PRESENT" | "LATE" | "ABSENT" | "LEAVE" | "REVIEW";
const MATCH: Record<Filter, (d: RegisterDay) => boolean> = {
  ALL: () => true,
  // Punched, or marked present on a day nobody punches (time/marking.py).
  PRESENT: (d) => hasWork(d) || d.status === "PRESENT" || d.status === "OFF_DAY_WORKED",
  LATE: (d) => d.late_by_minutes > 0,
  ABSENT: (d) => !hasWork(d) && d.status === "ABSENT",
  LEAVE: (d) => !hasWork(d) && d.status === "ON_LEAVE",
  REVIEW: (d) => d.needs_review,
};

/** Light tint per status for calendar cells. */
const CELL: Record<string, string> = {
  PRESENT: "border-success/25 bg-success/[0.06]",
  LATE: "border-warning/30 bg-warning/[0.07]",
  EARLY_DEPARTURE: "border-warning/30 bg-warning/[0.07]",
  HALF_DAY: "border-warning/30 bg-warning/[0.07]",
  ABSENT: "border-danger/25 bg-danger/[0.05]",
  MISSED_PUNCH: "border-danger/30 bg-danger/[0.07]",
  ON_LEAVE: "border-info/25 bg-info/[0.06]",
  HOLIDAY: "border-plum/25 bg-plum/[0.06]",
  OFF_DAY_WORKED: "border-plum/25 bg-plum/[0.06]",
  WEEKEND: "border-transparent bg-muted/60",
  UPCOMING: "border-line bg-surface opacity-50",
  NOT_MARKED: "border-dashed border-warning/40 bg-surface",
};

/** What to say for a day nobody worked. */
function restLabel(d: RegisterDay) {
  if (d.status === "ON_LEAVE") return d.leave_type ? `On leave · ${d.leave_type}` : "On leave";
  if (d.status === "HOLIDAY") return d.holiday_name ?? "Holiday";
  if (d.status === "WEEKEND") return "Weekly off";
  if (d.status === "UPCOMING") return "";
  // Attendance that is marked, not punched (time/marking.py).
  if (d.status === "NOT_MARKED") return "Not marked yet";
  if (d.status === "PRESENT" || d.status === "OFF_DAY_WORKED") return "Marked present · no punches";
  return "No check-in";
}

/**
 * One employee's month, day by day — as a list with a time bar per day, or as a calendar.
 * Click a day for the full picture; HR (corrections.write) can correct it from there.
 */
export function AttendanceRegister({ employmentId, canEdit, initialMonth, editDate, onEditDone, showName = true }: {
  employmentId: string;
  canEdit: boolean;
  initialMonth?: Date;
  /** Open this date (YYYY-MM-DD) straight in the editor once the month has loaded. */
  editDate?: string | null;
  onEditDone?: () => void;
  /** Show who the register belongs to (off inside the employee's own profile). */
  showName?: boolean;
}) {
  const { user } = useAuth();
  const canReview = !!user && (user.permissions.includes("*") || user.permissions.includes("corrections.approve"));
  const [month, setMonth] = useState(() => startOfMonth(initialMonth ?? new Date()));
  const [view, setView] = useState<"list" | "calendar">("list");
  const [filter, setFilter] = useState<Filter>("ALL");
  const [open, setOpen] = useState<{ date: string; edit: boolean } | null>(editDate ? { date: editDate, edit: true } : null);
  const from = format(month, "yyyy-MM-dd");
  const to = format(endOfMonth(month), "yyyy-MM-dd");
  const isCurrent = isSameMonth(month, new Date());

  const { data, isPending, isError, refetch } = useQuery<RegisterResponse>({
    queryKey: ["attendance-register", employmentId, from],
    queryFn: () => timeApi.register(employmentId, from, to),
  });
  const days = useMemo(() => data?.days ?? [], [data]);
  const range = useMemo(() => timelineRange(days.filter(hasWork)), [days]);
  // The list stops at today; upcoming days only add noise there (the calendar still shows them).
  const today = format(new Date(), "yyyy-MM-dd");
  const shown = days.filter((d) => d.work_date <= today && MATCH[filter](d));
  const openDay = days.find((d) => d.work_date === open?.date) ?? null;
  const editable = (d: RegisterDay) => canEdit && !d.is_locked && d.status !== "UPCOMING";
  const shift = days[0] ? `${days[0].shift_start}–${days[0].shift_end}` : null;

  const count = (f: Filter) => days.filter(MATCH[f]).length;
  const tiles: { filter: Filter; label: string; value: string | number; icon: typeof CircleCheck; tone: string }[] = [
    { filter: "PRESENT", label: "Present", value: count("PRESENT"), icon: CircleCheck, tone: "text-success" },
    { filter: "LATE", label: "Late", value: count("LATE"), icon: Timer, tone: "text-warning" },
    { filter: "ABSENT", label: "Absent", value: count("ABSENT"), icon: CircleX, tone: "text-danger" },
    { filter: "LEAVE", label: "On leave", value: count("LEAVE"), icon: Umbrella, tone: "text-info" },
    { filter: "REVIEW", label: "To review", value: count("REVIEW"), icon: ShieldAlert, tone: count("REVIEW") ? "text-warning" : "text-fg-subtle" },
  ];
  const workedTotal = days.reduce((s, d) => s + d.effective_minutes, 0);
  const otTotal = days.filter((d) => d.ot_status !== "REJECTED").reduce((s, d) => s + d.ot_minutes, 0);

  const closePanel = () => { setOpen(null); onEditDone?.(); };
  const summaryBadges = (
    <>
      {shift && <span className="badge badge-neutral"><Clock3 size={11} /> Shift {shift}</span>}
      {!isPending && <span className="badge badge-neutral"><Hourglass size={11} /> {fmtMins(workedTotal, "0h")} worked</span>}
      {!isPending && otTotal > 0 && <span className="badge badge-info"><CalendarPlus size={11} /> {fmtMins(otTotal)} overtime</span>}
    </>
  );

  return (
    <div className="card overflow-hidden">
      {/* Who */}
      {showName && (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 pt-4">
        {(
          <div className="flex min-w-0 items-center gap-3">
            {data ? <Avatar name={data.name} size="lg" employmentId={data.employment_id} /> : <Skeleton className="h-10 w-10 rounded-full" />}
            <div className="min-w-0 leading-tight">
              <p className="truncate text-[15px] font-semibold text-fg">{data?.name ?? "…"}</p>
              <p className="truncate text-xs text-fg-subtle">
                {[data?.employee_number, data?.department, data?.designation].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1.5 sm:ml-auto">{summaryBadges}</div>
      </div>
      )}

      {/* When */}
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
        <div className="flex items-center rounded-lg border border-line">
          <button className="btn-icon" onClick={() => setMonth((m) => subMonths(m, 1))} aria-label="Previous month"><ChevronLeft size={16} /></button>
          <span className="w-32 text-center text-[13px] font-semibold text-fg">{format(month, "MMMM yyyy")}</span>
          <button className="btn-icon" onClick={() => setMonth((m) => addMonths(m, 1))} disabled={isCurrent} aria-label="Next month"><ChevronRight size={16} /></button>
        </div>
        {!isCurrent && <button className="btn-ghost btn-sm" onClick={() => setMonth(startOfMonth(new Date()))}>This month</button>}
        {!showName && <div className="flex flex-wrap items-center gap-1.5">{summaryBadges}</div>}
        <div className="ml-auto">
          <Segmented
            value={view}
            onChange={setView}
            items={[{ value: "list", label: "List", icon: List }, { value: "calendar", label: "Calendar", icon: CalendarDays }]}
          />
        </div>
      </div>

      {/* The month at a glance — each tile filters the days */}
      <div className="no-scrollbar flex divide-x divide-line overflow-x-auto border-b border-line">
        {tiles.map((t) => (
          <button
            key={t.filter}
            onClick={() => setFilter((f) => (f === t.filter ? "ALL" : t.filter))}
            aria-pressed={filter === t.filter}
            className={`min-w-[6.5rem] flex-1 bg-surface px-4 py-3 text-left transition-colors hover:bg-muted/60 ${filter === t.filter ? "!bg-brand-500/[0.06] shadow-[inset_0_-2px_0_rgb(var(--brand-500))]" : ""}`}
          >
            <p className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-fg-subtle"><t.icon size={12} className={t.tone} />{t.label}</p>
            <p className="mt-0.5 text-lg font-semibold tabular-nums text-fg">{isPending ? "–" : t.value}</p>
          </button>
        ))}
      </div>

      {filter !== "ALL" && (
        <div className="flex items-center justify-between border-b border-line bg-panel px-5 py-2 text-xs text-fg-muted">
          <span>Showing {shown.length} {tiles.find((t) => t.filter === filter)?.label.toLowerCase()} day{shown.length === 1 ? "" : "s"}</span>
          <button className="font-medium text-accent hover:underline" onClick={() => setFilter("ALL")}>Show all days</button>
        </div>
      )}

      {isError ? (
        <div className="p-5">
          <Notice title="Couldn’t load attendance" action={<button className="btn-secondary btn-sm" onClick={() => refetch()}>Retry</button>}>
            The attendance service isn’t responding.
          </Notice>
        </div>
      ) : isPending ? (
        <div className="space-y-2 p-5">{Array.from({ length: 7 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}</div>
      ) : days.length === 0 ? (
        <EmptyState icon={CalendarDays} title="Not employed this month" description="Pick another month." />
      ) : view === "calendar" ? (
        <CalendarView days={days} month={month} highlight={MATCH[filter]} onOpen={(d) => setOpen({ date: d.work_date, edit: false })} />
      ) : shown.length === 0 ? (
        <EmptyState icon={CalendarDays} title="No days match" description="Choose another tile, or show all days." />
      ) : (
        <ul className="divide-y divide-line">
          {shown.map((d) => (
            <DayRow
              key={d.work_date} day={d} range={range} canEdit={editable(d)}
              onOpen={() => setOpen({ date: d.work_date, edit: false })}
              onEdit={() => setOpen({ date: d.work_date, edit: true })}
            />
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-5 py-2.5 text-[11px] text-fg-subtle">
        <span className="flex items-center gap-1.5"><span className="h-1.5 w-3 rounded-full bg-success" /> Worked</span>
        <span className="flex items-center gap-1.5"><span className="h-1.5 w-3 rounded-full bg-warning" /> Break</span>
        <span className="flex items-center gap-1.5"><span className="h-1.5 w-3 rounded-full bg-brand-500/25" /> Shift hours</span>
        <span className="ml-auto">Click a day for details{canEdit ? " or to edit it" : ""}.</span>
      </div>

      <DayPanel
        day={openDay}
        employeeName={data?.name ?? ""}
        employmentId={employmentId}
        canEdit={canEdit}
        canReview={canReview}
        startInEdit={open?.edit}
        onClose={closePanel}
      />
    </div>
  );
}

function DayRow({ day, range, canEdit, onOpen, onEdit }: {
  day: RegisterDay;
  range: { from: number; to: number };
  canEdit: boolean;
  onOpen: () => void;
  onEdit: () => void;
}) {
  const date = new Date(`${day.work_date}T00:00:00`);
  const worked = hasWork(day);
  const upcoming = day.status === "UPCOMING";
  const rest = !worked && (day.status === "WEEKEND" || day.status === "HOLIDAY" || day.status === "ON_LEAVE");
  const edited = day.punches.some((p) => p.is_corrected);
  return (
    <li className={`group relative ${rest ? "bg-muted/30" : ""} ${upcoming ? "opacity-50" : ""}`}>
      <button
        type="button" onClick={onOpen} disabled={upcoming}
        className="grid w-full grid-cols-[3.25rem_1fr_auto] items-center gap-x-4 gap-y-1 px-5 py-3 text-left transition-colors hover:bg-muted/50 disabled:cursor-default disabled:hover:bg-transparent sm:grid-cols-[3.25rem_9.5rem_1fr_7rem]"
        aria-label={`${format(date, "EEEE d MMMM")}: ${day.status.replace(/_/g, " ").toLowerCase()}`}
      >
        <span className="text-center leading-none">
          <span className={`block text-[11px] font-medium uppercase ${getDay(date) === 0 || getDay(date) === 6 ? "text-fg-subtle" : "text-fg-muted"}`}>{format(date, "EEE")}</span>
          <span className="mt-1 block text-lg font-semibold tabular-nums text-fg">{format(date, "d")}</span>
        </span>

        <span className="flex flex-col items-start gap-1">
          {upcoming ? <span className="text-xs text-fg-subtle">Upcoming</span> : <StatusBadge status={day.status} />}
          <span className="flex flex-wrap gap-1">
            {day.needs_review && <span className="badge badge-warning text-[10px]"><ShieldAlert size={10} /> Review</span>}
            {edited && <span className="badge badge-neutral text-[10px]">Edited</span>}
          </span>
        </span>

        <span className="text-right sm:order-last">
          {worked && (
            <>
              <span className="block text-[15px] font-semibold tabular-nums text-fg">{day.last_punch_out ? fmtMins(day.effective_minutes, "0m") : "—"}</span>
              <span className="block text-[11px] text-fg-subtle">
                {!day.last_punch_out ? "in progress"
                  : day.ot_minutes > 0 ? <span className="text-info">+{fmtMins(day.ot_minutes)} OT</span>
                  : day.comp_off_days > 0 ? <span className="text-plum">{day.comp_off_days} comp-off</span>
                  : day.break_minutes > 0 ? `${fmtMins(day.break_minutes)} away` : "worked"}
              </span>
            </>
          )}
        </span>
        <span className="col-span-3 min-w-0 sm:col-span-1">
          {worked ? (
            <>
              <span className="flex items-center gap-2 text-[13px] tabular-nums text-fg">
                {punchTime(day.first_punch_in, day)}
                <span className="text-fg-subtle">→</span>
                {day.last_punch_out ? punchTime(day.last_punch_out, day) : <span className="badge badge-success text-[10px]">Still in</span>}
                {day.late_by_minutes > 0 && <span className="text-[11px] text-warning">{fmtMins(day.late_by_minutes)} late</span>}
                {day.early_departure_minutes > 0 && <span className="text-[11px] text-warning">{fmtMins(day.early_departure_minutes)} early</span>}
              </span>
              <span className="mt-1.5 block"><DayTimeline day={day} range={range} /></span>
            </>
          ) : (
            <span className="text-[13px] text-fg-subtle">{restLabel(day)}</span>
          )}
        </span>

      </button>
      {canEdit && (
        <button
          type="button" onClick={onEdit} aria-label={`Edit ${day.work_date}`}
          className="btn-secondary btn-sm absolute right-3 top-1/2 -translate-y-1/2 opacity-0 shadow-sm transition-opacity focus:opacity-100 group-hover:opacity-100"
        >
          <Pencil size={13} /> Edit
        </button>
      )}
    </li>
  );
}

function CalendarView({ days, month, highlight, onOpen }: {
  days: RegisterDay[];
  month: Date;
  highlight: (d: RegisterDay) => boolean;
  onOpen: (d: RegisterDay) => void;
}) {
  const lead = (getDay(month) + 6) % 7; // Monday first
  const byDate = new Map(days.map((d) => [d.work_date, d]));
  const all = Array.from({ length: endOfMonth(month).getDate() }, (_, i) => format(new Date(month.getFullYear(), month.getMonth(), i + 1), "yyyy-MM-dd"));
  return (
    <div className="p-4 sm:p-5">
      <div className="mb-2 grid grid-cols-7 gap-1.5 text-center text-[11px] font-medium text-fg-subtle">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <span key={d}>{d}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-1.5">
        {Array.from({ length: lead }).map((_, i) => <div key={`lead-${i}`} />)}
        {all.map((iso) => {
          const d = byDate.get(iso);
          const dim = d && !highlight(d);
          return (
            <button
              key={iso} type="button" disabled={!d || d.status === "UPCOMING"} onClick={() => d && onOpen(d)}
              className={`flex min-h-[4.5rem] flex-col rounded-lg border p-1.5 text-left transition hover:ring-2 hover:ring-brand-500/30 disabled:hover:ring-0 sm:min-h-[5.5rem] sm:p-2 ${d ? CELL[d.status] ?? "border-line bg-surface" : "border-transparent"} ${dim ? "opacity-30" : ""}`}
            >
              <span className="flex items-center justify-between">
                <span className="text-xs font-semibold tabular-nums text-fg-muted">{Number(iso.slice(8))}</span>
                {d?.needs_review && <ShieldAlert size={12} className="text-warning" />}
              </span>
              {d && hasWork(d) ? (
                <span className="mt-auto hidden text-[10px] leading-tight tabular-nums text-fg-muted sm:block">
                  {shortTime(d.first_punch_in, d)}–{d.last_punch_out ? shortTime(d.last_punch_out, d) : "…"}
                  <span className="block text-[11px] font-semibold text-fg">{d.last_punch_out ? fmtMins(d.effective_minutes, "0m") : "Still in"}</span>
                </span>
              ) : d && d.status !== "UPCOMING" ? (
                <span className="mt-auto truncate text-[10px] text-fg-subtle">{restLabel(d)}</span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

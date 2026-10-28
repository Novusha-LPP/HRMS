import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { addDays, format, parseISO } from "date-fns";
import { CalendarPlus, Check, ChevronLeft, ChevronRight, ClipboardCheck, Clock, Search, Settings2, X } from "lucide-react";
import { groupsApi, markingApi, type MarkStatus, type MarkingRow } from "../api/marking";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Avatar } from "../components/ui/Avatar";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Sheet } from "../components/ui/Overlay";
import { EmptyState, Notice, Skeleton } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { clock12, zonedParts } from "../lib/zonedTime";

/** A row's unsaved change: a mark (with optional times), or status null to clear it. */
interface Draft { status: MarkStatus | null; punch_in: string; punch_out: string }

const SUMMARY: { key: string; label: string }[] = [
  { key: "PRESENT", label: "Present" },
  { key: "ABSENT", label: "Absent" },
  { key: "NOT_MARKED", label: "Not marked" },
  { key: "ON_LEAVE", label: "On leave" },
];
const WORKED = new Set(["PRESENT", "LATE", "HALF_DAY", "EARLY_DEPARTURE", "OFF_DAY_WORKED", "MISSED_PUNCH"]);

/** What the row holds now, in the same shape as a draft. */
function saved(row: MarkingRow): Draft {
  const time = (iso: string | null) => (iso ? zonedParts(iso, row.timezone).time : "");
  if (row.has_punches) return { status: null, punch_in: "", punch_out: "" };
  if (row.punch_in) return { status: "PRESENT", punch_in: time(row.punch_in), punch_out: time(row.punch_out) };
  if (row.status === "ABSENT") return { status: "ABSENT", punch_in: "", punch_out: "" };
  if (WORKED.has(row.status)) return { status: "PRESENT", punch_in: "", punch_out: "" };
  return { status: null, punch_in: "", punch_out: "" };
}
const same = (a: Draft, b: Draft) => a.status === b.status && a.punch_in === b.punch_in && a.punch_out === b.punch_out;
const hours = (m: number) => `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;

/**
 * The daily sheet for attendance groups (guards, drivers, cleaners…): pick a day, set each
 * person present or absent — with in/out times if you have them — and save once. Leave is
 * recorded as a range. Rows of groups you can only view are read-only.
 * URL: ?date=YYYY-MM-DD&group=<group id>
 */
export function MarkAttendancePage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();
  const canManage = !!user && (user.permissions.includes("*") || user.permissions.includes("attendance.groups.manage"));
  const today = format(new Date(), "yyyy-MM-dd");
  const [params, setParams] = useSearchParams();
  const day = params.get("date") ?? today;
  const group = params.get("group") ?? "";
  const [draft, setDraft] = useState<Record<string, Draft>>({});
  const [remark, setRemark] = useState("");
  const [query, setQuery] = useState("");
  const [leaveFor, setLeaveFor] = useState<MarkingRow | null>(null);

  const groups = useQuery({ queryKey: ["attendance-groups"], queryFn: groupsApi.list });
  const sheet = useQuery({ queryKey: ["marking", day, group], queryFn: () => markingApi.day(day, group) });
  const rows = useMemo(() => sheet.data?.rows ?? [], [sheet.data]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? rows.filter((r) => `${r.name} ${r.employee_number ?? ""}`.toLowerCase().includes(q)) : rows;
  }, [rows, query]);
  const changes = Object.keys(draft).length;
  const anyMarkable = rows.some((r) => r.can_mark);

  const save = useMutation({
    mutationFn: () => markingApi.mark(
      day,
      Object.entries(draft).map(([employment_id, d]) => ({
        employment_id,
        status: d.status,
        ...(d.status === "PRESENT" && d.punch_in ? { punch_in: d.punch_in } : {}),
        ...(d.status === "PRESENT" && d.punch_in && d.punch_out ? { punch_out: d.punch_out } : {}),
      })),
      remark.trim(),
    ),
    onSuccess: (result) => {
      toast.success("Attendance saved", `${result.changed} changed · ${format(parseISO(day), "d MMM yyyy")}`);
      setDraft({});
      setRemark("");
      qc.invalidateQueries({ queryKey: ["marking"] });
      qc.invalidateQueries({ queryKey: ["register"] });
    },
    onError: (e) => toast.error("Nothing was saved", errorMessage(e)),
  });

  const move = (next: Partial<Record<"date" | "group", string>>) => {
    if (changes && !window.confirm("You have unsaved marks. Discard them?")) return;
    setDraft({});
    setParams((p) => {
      const n = new URLSearchParams(p);
      for (const [k, v] of Object.entries(next)) {
        if (v) n.set(k, v); else n.delete(k);
      }
      return n;
    });
  };
  const shiftDay = (by: number) => {
    const next = format(addDays(parseISO(day), by), "yyyy-MM-dd");
    if (next <= today) move({ date: next });
  };

  const change = (row: MarkingRow, next: Draft) => setDraft((d) => {
    const n = { ...d };
    if (same(next, saved(row))) delete n[row.employment_id];
    else n[row.employment_id] = next;
    return n;
  });
  const markRestPresent = () => setDraft((d) => {
    const n = { ...d };
    for (const r of visible) {
      if (r.can_mark && r.status === "NOT_MARKED" && !(r.employment_id in n)) n[r.employment_id] = { status: "PRESENT", punch_in: "", punch_out: "" };
    }
    return n;
  });
  const unmarked = visible.filter((r) => r.can_mark && r.status === "NOT_MARKED" && !(r.employment_id in draft)).length;

  return (
    <>
      <PageHeader
        title="Mark attendance"
        description="For groups that don't punch — guards, drivers, cleaners: mark each day present or absent, add in and out times if you have them, and record leave from one date to another."
        actions={canManage ? <Link to="/attendance/groups" className="btn-secondary"><Settings2 size={15} /> Manage groups</Link> : undefined}
      />
      <div className="card mb-4 flex flex-col gap-3 p-4 lg:flex-row lg:items-end">
        <div>
          <label className="label" htmlFor="mark-date">Day</label>
          <div className="mt-1 flex items-center gap-1">
            <button type="button" className="btn-ghost btn-sm" aria-label="Previous day" onClick={() => shiftDay(-1)}><ChevronLeft size={16} /></button>
            <input id="mark-date" type="date" className="input w-40" value={day} max={today} onChange={(e) => e.target.value && move({ date: e.target.value })} />
            <button type="button" className="btn-ghost btn-sm" aria-label="Next day" disabled={day >= today} onClick={() => shiftDay(1)}><ChevronRight size={16} /></button>
          </div>
        </div>
        <div className="min-w-0 flex-1 lg:max-w-xs">
          <label className="label" htmlFor="mark-group">Group</label>
          <select id="mark-group" className="input mt-1" value={group} onChange={(e) => move({ group: e.target.value })} disabled={groups.isPending}>
            <option value="">All my groups</option>
            {(groups.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}{g.my_access === "VIEW" ? " (view only)" : ""}</option>)}
          </select>
        </div>
        <div className="relative min-w-0 flex-1 lg:max-w-xs">
          <label className="label" htmlFor="mark-search">Search</label>
          <Search size={14} className="pointer-events-none absolute bottom-3 left-3 text-fg-subtle" />
          <input id="mark-search" className="input mt-1 pl-9" placeholder="Name or ID" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {sheet.isError && <div className="mb-4"><Notice title="Couldn’t load the day" action={<button className="btn-secondary btn-sm" onClick={() => sheet.refetch()}>Retry</button>}>
        {errorMessage(sheet.error)}
      </Notice></div>}

      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          {SUMMARY.map((s) => {
            const counts = sheet.data?.counts ?? {};
            // Present counts everyone who worked: late, half day and off-day work included.
            const n = s.key === "PRESENT"
              ? Object.entries(counts).filter(([k]) => WORKED.has(k)).reduce((a, [, v]) => a + v, 0)
              : counts[s.key] ?? 0;
            return <StatusBadge key={s.key} status={s.key} label={`${s.label} ${n}`} />;
          })}
          {anyMarkable && (
            <button type="button" className="btn-secondary btn-sm ml-auto" disabled={!unmarked} onClick={markRestPresent}>
              <Check size={14} /> {unmarked ? `Mark the rest present (${unmarked})` : "Everyone is marked"}
            </button>
          )}
        </div>
        {sheet.isPending ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={ClipboardCheck}
            title="No one to mark"
            description={canManage
              ? "Nobody is in an attendance group on this day. Create groups such as Guards or Drivers and add people under Manage groups."
              : "You haven't been given a group, or nobody is in yours on this day. Ask HR to add you to a group."}
          />
        ) : (
          <ul className="divide-y divide-line">
            {visible.map((row) => (
              <MarkRow
                key={row.employment_id}
                row={row}
                showGroup={!group}
                draft={draft[row.employment_id]}
                onChange={(next) => change(row, next)}
                onLeave={() => setLeaveFor(row)}
              />
            ))}
          </ul>
        )}
      </div>

      {changes > 0 && (
        <div className="sticky bottom-4 z-10 mt-4 flex flex-col gap-3 rounded-xl border border-line bg-surface p-3 shadow-lg sm:flex-row sm:items-center">
          <span className="text-[13px] font-medium text-fg">{changes} unsaved {changes === 1 ? "change" : "changes"}</span>
          <input className="input flex-1" placeholder="Remark for these marks (optional)" maxLength={500} value={remark} onChange={(e) => setRemark(e.target.value)} />
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={() => setDraft({})} disabled={save.isPending}>Discard</button>
            <button type="button" className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}

      <RecordLeaveSheet row={leaveFor} defaultDate={day} onClose={() => setLeaveFor(null)} />
    </>
  );
}

function MarkRow({ row, showGroup, draft, onChange, onLeave }: {
  row: MarkingRow;
  showGroup: boolean;
  draft: Draft | undefined;
  onChange: (next: Draft) => void;
  onLeave: () => void;
}) {
  const current = draft ?? saved(row);
  const [showTimes, setShowTimes] = useState(!!current.punch_in);
  const pending = !!draft;
  const shown = pending
    ? current.status === null ? "NOT_MARKED" : current.status === "PRESENT" && row.is_off_day ? "OFF_DAY_WORKED" : current.status
    : row.status;
  const detail = row.blocked_reason
    ?? (row.holiday_name ? `Holiday · ${row.holiday_name}` : row.is_off_day ? "Day off — mark present only if they worked" : null);
  const set = (patch: Partial<Draft>) => onChange({ ...current, ...patch });
  const savedTimes = !pending && row.punch_in
    ? `${clock12(row.punch_in, row.timezone)}${row.punch_out ? ` – ${clock12(row.punch_out, row.timezone)}` : " – still in"} · ${hours(row.worked_minutes)}${row.late_by_minutes ? ` · ${row.late_by_minutes} min late` : ""}`
    : null;

  return (
    <li className={`flex flex-col gap-3 px-4 py-3 ${pending ? "bg-brand-500/[0.04]" : ""}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <Avatar name={row.name} size="sm" employmentId={row.employment_id} />
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[13px] font-medium text-fg">
              {row.name}
              {showGroup && <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[11px] font-normal text-fg-muted">{row.group_name}</span>}
            </p>
            <p className="truncate text-xs text-fg-subtle">{row.employee_number}{row.department ? ` · ${row.department}` : ""}</p>
            {savedTimes && <p className="truncate text-[11px] text-fg-muted"><Clock size={11} className="mr-1 inline" />{savedTimes}</p>}
            {row.mark && !pending && (
              <p className="truncate text-[11px] text-fg-subtle">
                {row.mark.status ? `Marked ${row.mark.status.toLowerCase()}` : "Mark cleared"}
                {row.mark.marked_by ? ` by ${row.mark.marked_by}` : ""} · {format(parseISO(row.mark.marked_at), "d MMM, HH:mm")}
                {row.mark.remark ? ` · “${row.mark.remark}”` : ""}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          <StatusBadge status={shown} label={row.leave_type && shown === "ON_LEAVE" ? `On leave · ${row.leave_type}` : undefined} />
          {detail && <span className="text-[11px] text-fg-subtle">{detail}</span>}
          {row.can_mark && (
            <div className="seg" role="radiogroup" aria-label={`Mark ${row.name}`}>
              <button type="button" role="radio" aria-checked={current.status === "PRESENT"} data-active={current.status === "PRESENT"} className="seg-item" onClick={() => set({ status: "PRESENT" })}>
                <Check size={13} /> Present
              </button>
              <button
                type="button" role="radio" aria-checked={current.status === "ABSENT"} data-active={current.status === "ABSENT"} className="seg-item"
                disabled={row.is_off_day} title={row.is_off_day ? "A day off can't be marked absent" : undefined}
                onClick={() => { setShowTimes(false); set({ status: "ABSENT", punch_in: "", punch_out: "" }); }}
              >
                <X size={13} /> Absent
              </button>
              {current.status !== null && (
                <button type="button" className="seg-item" aria-label={`Clear ${row.name}'s mark`} onClick={() => { setShowTimes(false); set({ status: null, punch_in: "", punch_out: "" }); }}>Clear</button>
              )}
            </div>
          )}
          {row.can_mark && current.status === "PRESENT" && !showTimes && (
            <button type="button" className="btn-ghost btn-sm" onClick={() => setShowTimes(true)}><Clock size={14} /> Add times</button>
          )}
          {row.access === "MARK" && !row.has_punches && !row.is_locked && (
            <button type="button" className="btn-ghost btn-sm" onClick={onLeave}><CalendarPlus size={14} /> Leave</button>
          )}
        </div>
      </div>
      {row.can_mark && current.status === "PRESENT" && showTimes && (
        <div className="flex flex-wrap items-end gap-3 sm:pl-11">
          <div>
            <label className="label" htmlFor={`in-${row.employment_id}`}>In</label>
            <input id={`in-${row.employment_id}`} type="time" className="input w-32" value={current.punch_in} onChange={(e) => set({ punch_in: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor={`out-${row.employment_id}`}>Out (optional)</label>
            <input id={`out-${row.employment_id}`} type="time" className="input w-32" value={current.punch_out} disabled={!current.punch_in} onChange={(e) => set({ punch_out: e.target.value })} />
          </div>
          <p className="pb-2 text-[11px] text-fg-subtle">
            Hours, late and overtime follow their policy. An out time earlier than the in time is the next morning.
          </p>
          <button type="button" className="btn-ghost btn-sm mb-1" onClick={() => { setShowTimes(false); set({ punch_in: "", punch_out: "" }); }}>Remove times</button>
        </div>
      )}
    </li>
  );
}

function RecordLeaveSheet({ row, defaultDate, onClose }: { row: MarkingRow | null; defaultDate: string; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const types = useQuery({ queryKey: ["marking-leave-types"], queryFn: markingApi.leaveTypes, enabled: !!row });
  const [leaveType, setLeaveType] = useState("");
  const [from, setFrom] = useState(defaultDate);
  const [to, setTo] = useState(defaultDate);
  const [reason, setReason] = useState("");
  const [shownFor, setShownFor] = useState<string | null>(null);
  if (row && shownFor !== row.employment_id) {
    // A fresh form for each person.
    setShownFor(row.employment_id);
    setLeaveType("");
    setFrom(defaultDate);
    setTo(defaultDate);
    setReason("");
  }

  const record = useMutation({
    mutationFn: () => markingApi.recordLeave({
      employment_id: row!.employment_id,
      leave_type_id: leaveType,
      from_date: from,
      to_date: to,
      reason: reason.trim() || undefined,
    }),
    onSuccess: (app) => {
      toast.success("Leave recorded", `${row?.name} · ${app.days_requested} day(s)`);
      qc.invalidateQueries({ queryKey: ["marking"] });
      qc.invalidateQueries({ queryKey: ["register"] });
      qc.invalidateQueries({ queryKey: ["leave"] });
      onClose();
    },
    onError: (e) => toast.error("Leave wasn’t recorded", errorMessage(e)),
  });
  const valid = !!leaveType && !!from && !!to && to >= from;
  const submit = (e: FormEvent) => { e.preventDefault(); if (valid) record.mutate(); };

  return (
    <Sheet
      open={!!row}
      onClose={onClose}
      title="Record leave"
      description={row ? `${row.name}${row.employee_number ? ` · ${row.employee_number}` : ""}. Recorded as approved leave, using their balance.` : undefined}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" type="submit" form="record-leave" disabled={!valid || record.isPending}>
            {record.isPending ? "Recording…" : "Record leave"}
          </button>
        </>
      }
    >
      <form id="record-leave" onSubmit={submit} className="space-y-4">
        <div>
          <label className="label" htmlFor="rl-type">Leave type</label>
          <select id="rl-type" className="input" value={leaveType} onChange={(e) => setLeaveType(e.target.value)} disabled={types.isPending}>
            <option value="">Choose a leave type</option>
            {(types.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}{t.is_paid ? "" : " (unpaid)"}</option>)}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="rl-from">From</label>
            <input id="rl-from" type="date" className="input" value={from} onChange={(e) => { setFrom(e.target.value); if (to < e.target.value) setTo(e.target.value); }} />
          </div>
          <div>
            <label className="label" htmlFor="rl-to">To</label>
            <input id="rl-to" type="date" className="input" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="rl-reason">Reason (optional)</label>
          <textarea id="rl-reason" className="input min-h-20" maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <p className="text-xs text-fg-subtle">
          An absent mark on these days is cleared. Days marked present must be cleared first. If there isn’t enough
          balance, choose an unpaid leave type.
        </p>
      </form>
    </Sheet>
  );
}

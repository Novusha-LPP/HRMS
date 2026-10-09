import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  LogIn, LogOut, Coffee, Pencil, Plus, Trash2, ShieldAlert, Lock, CalendarX2, Sun, SunMedium,
  TriangleAlert, Info, ArrowLeft, CircleCheck,
} from "lucide-react";
import { timeApi, REVIEW_FLAG_LABEL, type RegisterDay } from "../../api/time";
import { Sheet } from "../ui/Overlay";
import { StatusBadge } from "../ui/StatusBadge";
import { useToast, errorMessage } from "../ui/Toast";
import { DayTimeline } from "./DayTimeline";
import {
  PUNCH_LABEL, buildPunches, expectedResult, fmtMins, formFromPunches, keepOriginals, punchTime, rowKey,
  shiftWindow, timelineRange, type AwayKind, type DayForm,
} from "./registerModel";

const REASONS = [
  "Forgot to check in / out",
  "Biometric / device problem",
  "On official duty outside",
  "Approved by reporting manager",
];

const longDate = (d: string) => format(new Date(`${d}T00:00:00`), "EEEE, d MMMM yyyy");

/**
 * Everything about one day of one employee: what happened (times, punches, flags) and — for HR —
 * a plain form to correct it: check-in, check-out and any time away, with a reason.
 */
export function DayPanel({ day, employeeName, employmentId, canEdit, canReview, startInEdit, onClose }: {
  day: RegisterDay | null;
  employeeName: string;
  employmentId: string;
  canEdit: boolean;
  canReview: boolean;
  startInEdit?: boolean;
  onClose: () => void;
}) {
  if (!day) return null;
  return (
    <DayPanelContent
      key={`${employmentId}-${day.work_date}`}
      day={day} employeeName={employeeName} employmentId={employmentId}
      canEdit={canEdit} canReview={canReview} startInEdit={!!startInEdit} onClose={onClose}
    />
  );
}

function whyNotEditable(day: RegisterDay, canEdit: boolean) {
  if (!canEdit) return null;
  if (day.is_locked) return "This day is in a locked payroll period and can't be changed.";
  if (day.status === "UPCOMING") return "Future days can't be edited.";
  return null;
}

function DayPanelContent({ day, employeeName, employmentId, canEdit, canReview, startInEdit, onClose }: {
  day: RegisterDay; employeeName: string; employmentId: string;
  canEdit: boolean; canReview: boolean; startInEdit: boolean; onClose: () => void;
}) {
  const blocked = whyNotEditable(day, canEdit);
  const editable = canEdit && !blocked;
  const [mode, setMode] = useState<"view" | "edit">(startInEdit && editable ? "edit" : "view");
  const initial = useMemo(() => formFromPunches(day), [day]);
  const [form, setForm] = useState<DayForm>(() => initial ?? { checkIn: "", checkOut: "", away: [] });
  const [reason, setReason] = useState("");
  const built = useMemo(() => buildPunches(form, day), [form, day]);
  const result = expectedResult(built, day);
  const qc = useQueryClient();
  const toast = useToast();

  const refresh = () => {
    for (const key of ["attendance-register", "daily-analysis", "attendance-days", "pending-overtime", "corrections"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
  const save = useMutation({
    mutationFn: () => timeApi.editDay(employmentId, day.work_date, keepOriginals(built.punches, day), reason.trim()),
    onSuccess: (saved) => {
      toast.success("Attendance updated", saved.first_punch_in
        ? `${employeeName}: ${fmtMins(saved.effective_minutes, "0m")} worked on ${format(new Date(`${day.work_date}T00:00:00`), "d MMM")}.`
        : `${employeeName} marked absent on ${format(new Date(`${day.work_date}T00:00:00`), "d MMM")}.`);
      refresh();
      setMode("view");
      setReason("");
    },
    onError: (e) => toast.error("Couldn’t save the change", errorMessage(e)),
  });
  const accept = useMutation({
    mutationFn: () => timeApi.reviewDay(day.attendance_day_id!),
    onSuccess: () => { toast.success("Day accepted as recorded"); refresh(); },
    onError: (e) => toast.error("Couldn’t accept the day", errorMessage(e)),
  });

  const unchanged = JSON.stringify(keepOriginals(built.punches, day)) === JSON.stringify(day.punches.map((p) => ({ punch_type: p.punch_type, punched_at: p.punched_at })));
  const canSave = !unchanged && built.problems.length === 0 && reason.trim().length >= 3 && !save.isPending;

  const footer = mode === "view" ? (
    <div className="flex w-full items-center justify-between gap-3">
      <p className="text-xs text-fg-subtle">{blocked ?? (canEdit ? "" : "Only HR can change attendance.")}</p>
      {editable && (
        <button className="btn-primary" onClick={() => setMode("edit")}>
          <Pencil size={14} /> Edit attendance
        </button>
      )}
    </div>
  ) : (
    <div className="flex w-full items-center justify-between gap-3">
      <button className="btn-ghost" onClick={() => { setMode("view"); setForm(initial ?? { checkIn: "", checkOut: "", away: [] }); }}>
        <ArrowLeft size={14} /> Back
      </button>
      <div className="flex items-center gap-3">
        {!canSave && !save.isPending && (
          <span className="hidden text-xs text-fg-subtle sm:inline">
            {unchanged ? "No changes yet" : built.problems.length ? "Fix the times above" : "Add a reason to save"}
          </span>
        )}
        <button className="btn-primary" disabled={!canSave} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save changes"}
        </button>
      </div>
    </div>
  );

  return (
    <Sheet
      open
      onClose={onClose}
      className="max-w-lg"
      title={mode === "edit" ? "Edit attendance" : longDate(day.work_date)}
      description={`${employeeName} · ${mode === "edit" ? `${longDate(day.work_date)} · ` : ""}Shift ${day.shift_start}–${day.shift_end}`}
      footer={footer}
    >
      {mode === "view" ? (
        <DayView day={day} canReview={canReview} accepting={accept.isPending} onAccept={() => accept.mutate()} />
      ) : (
        <DayEditForm
          day={day} form={form} setForm={setForm} reason={reason} setReason={setReason}
          built={built} result={result} unusual={initial === null}
        />
      )}
    </Sheet>
  );
}

// ─── View ────────────────────────────────────────────────────────────────────

function Stat({ label, value, tone, sub }: { label: string; value: ReactNode; tone?: string; sub?: ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
      <p className="text-[11px] text-fg-subtle">{label}</p>
      <p className={`mt-0.5 text-[15px] font-semibold tabular-nums ${tone ?? "text-fg"}`}>{value}</p>
      {sub && <p className="text-[11px] text-fg-subtle">{sub}</p>}
    </div>
  );
}

function DayView({ day, canReview, accepting, onAccept }: {
  day: RegisterDay; canReview: boolean; accepting: boolean; onAccept: () => void;
}) {
  const range = timelineRange([day]);
  const worked = !!day.first_punch_in;
  const otLabel: Record<string, string> = {
    PENDING: "Pending approval", APPROVED: "Approved", REJECTED: "Rejected", INFO: "Shown only — no OT policy", NONE: "",
  };
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={day.status} />
        {day.holiday_name && <span className="badge badge-plum">{day.holiday_name}</span>}
        {day.leave_type && <span className="badge badge-info">{day.leave_type}</span>}
        {day.is_locked && <span className="badge badge-neutral"><Lock size={10} /> Locked</span>}
      </div>

      {day.review_flags.length > 0 && (
        <div className={`rounded-lg p-3 text-[13px] ${day.needs_review ? "bg-warning/10 text-warning" : "bg-muted text-fg-muted"}`}>
          <p className="flex items-center gap-1.5 font-semibold">
            {day.needs_review ? <ShieldAlert size={15} /> : <CircleCheck size={15} />}
            {day.needs_review ? "Needs HR review" : "Reviewed by HR"}
          </p>
          <p className="mt-1">
            {day.review_flags.map((f) => REVIEW_FLAG_LABEL[f]).join(" · ")}
            {day.needs_review ? ". Overtime and comp-off are on hold until the times are corrected or accepted." : "."}
          </p>
          {day.needs_review && canReview && day.attendance_day_id && (
            <button className="btn-secondary btn-sm mt-2.5" disabled={accepting} onClick={onAccept}>
              {accepting ? "Saving…" : "Accept as recorded"}
            </button>
          )}
        </div>
      )}

      {worked ? (
        <>
          <div className="rounded-xl border border-line bg-panel p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <span className="text-[13px] font-medium text-fg">
                {punchTime(day.first_punch_in, day)} – {day.last_punch_out ? punchTime(day.last_punch_out, day) : "still checked in"}
              </span>
              <span className="text-xs text-fg-subtle">shift {day.shift_start}–{day.shift_end}</span>
            </div>
            <DayTimeline day={day} range={range} size="lg" />
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-subtle">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-success" /> Worked</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-warning" /> Break</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-brand-500/25" /> Shift</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <Stat label="Worked" value={fmtMins(day.effective_minutes, "0m")} sub={`of ${fmtMins(day.standard_minutes)} standard`} />
            <Stat label="Time away" value={fmtMins(day.break_minutes, "None")} sub={`total ${fmtMins(day.gross_minutes, "0m")}`} />
            <Stat
              label="Late / early"
              value={day.late_by_minutes || day.early_departure_minutes
                ? [day.late_by_minutes && `${fmtMins(day.late_by_minutes)} late`, day.early_departure_minutes && `${fmtMins(day.early_departure_minutes)} early`].filter(Boolean).join(" · ")
                : "On time"}
              tone={day.late_by_minutes || day.early_departure_minutes ? "text-warning" : "text-success"}
            />
            {day.ot_minutes > 0 && <Stat label="Overtime" value={fmtMins(day.ot_minutes)} sub={otLabel[day.ot_status]} tone="text-info" />}
            {day.comp_off_days > 0 && <Stat label="Comp-off earned" value={`${day.comp_off_days} day${day.comp_off_days === 1 ? "" : "s"}`} tone="text-plum" />}
          </div>
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-line px-4 py-6 text-center">
          <p className="text-[13px] font-medium text-fg">
            {day.status === "ON_LEAVE" ? `On leave${day.leave_type ? ` — ${day.leave_type}` : ""}`
              : day.status === "HOLIDAY" ? `Holiday${day.holiday_name ? ` — ${day.holiday_name}` : ""}`
              : day.status === "WEEKEND" ? "Weekly off"
              : day.status === "UPCOMING" ? "This day hasn’t happened yet"
              : "No check-in recorded"}
          </p>
          <p className="mt-1 text-xs text-fg-subtle">No punches on this day.</p>
        </div>
      )}

      {day.punches.length > 0 && (
        <div>
          <p className="eyebrow mb-2">Punch history</p>
          <ol className="divide-y divide-line rounded-xl border border-line">
            {day.punches.map((p) => {
              const Icon = p.punch_type === "IN" ? LogIn : p.punch_type === "OUT" ? LogOut : Coffee;
              return (
                <li key={p.id} className="flex items-start gap-3 px-3.5 py-2.5">
                  <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full ${p.punch_type === "IN" ? "bg-success/10 text-success" : p.punch_type === "OUT" ? "bg-muted text-fg-muted" : "bg-warning/10 text-warning"}`}>
                    <Icon size={13} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center justify-between gap-2 text-[13px]">
                      <span className="font-medium text-fg">{PUNCH_LABEL[p.punch_type] ?? p.punch_type}</span>
                      <span className="tabular-nums text-fg">{punchTime(p.punched_at, day)}</span>
                    </p>
                    <p className="truncate text-xs text-fg-subtle" title={p.correction_reason ?? undefined}>
                      {p.is_corrected ? `Corrected${p.correction_reason ? ` — ${p.correction_reason}` : ""}` : p.source === "WEB" ? "Web clock" : p.source === "MOBILE" ? "Mobile app" : p.source === "DEVICE" ? "Biometric device" : p.source.toLowerCase()}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}

// ─── Edit ────────────────────────────────────────────────────────────────────

function TimeField({ id, label, value, onChange, hint, nextDay, optional, clearable }: {
  id: string; label: string; value: string; onChange: (v: string) => void;
  hint?: string; nextDay?: boolean; optional?: boolean; clearable?: boolean;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label className="label !mb-0" htmlFor={id}>
          {label}{optional && <span className="ml-1 font-normal text-fg-subtle">(optional)</span>}
        </label>
        <span className="flex items-center gap-2">
          {nextDay && value && <span className="badge badge-info text-[10px]">next day</span>}
          {value && clearable && (
            <button type="button" className="text-[11px] font-medium text-fg-subtle hover:text-danger" onClick={() => onChange("")}>
              Clear
            </button>
          )}
        </span>
      </div>
      <input id={id} type="time" className="input tabular-nums" value={value} onChange={(e) => onChange(e.target.value)} />
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
}

function DayEditForm({ day, form, setForm, reason, setReason, built, result, unusual }: {
  day: RegisterDay;
  form: DayForm;
  setForm: (f: DayForm | ((f: DayForm) => DayForm)) => void;
  reason: string;
  setReason: (r: string) => void;
  built: ReturnType<typeof buildPunches>;
  result: ReturnType<typeof expectedResult>;
  unusual: boolean;
}) {
  const shift = shiftWindow(day);
  const clock = (m: number) => `${String(Math.floor((m % 1440) / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  // The policy break placed in the middle of the shift.
  const breakFrom = shift.from + Math.round((shift.to - shift.from - day.policy_break_minutes) / 2 / 30) * 30;
  const breakTo = breakFrom + day.policy_break_minutes;
  const presets = [
    { label: "Full shift", detail: `${day.shift_start} – ${day.shift_end}`, icon: Sun, form: { checkIn: day.shift_start, checkOut: day.shift_end, away: [] } },
    ...(day.policy_break_minutes > 0 ? [{
      label: "Shift + break", detail: `break ${clock(breakFrom)} – ${clock(breakTo)}`, icon: SunMedium,
      form: { checkIn: day.shift_start, checkOut: day.shift_end, away: [{ key: rowKey(), kind: "BREAK" as const, from: clock(breakFrom), to: clock(breakTo) }] },
    }] : []),
    { label: "Absent", detail: "No punches", icon: CalendarX2, form: { checkIn: "", checkOut: "", away: [] } },
  ];
  const addAway = (kind: AwayKind) => setForm((f) => ({ ...f, away: [...f.away, { key: rowKey(), kind, from: "", to: "" }] }));
  const setAway = (key: string, patch: Partial<DayForm["away"][number]>) =>
    setForm((f) => ({ ...f, away: f.away.map((r) => (r.key === key ? { ...r, ...patch } : r)) }));
  const absent = !form.checkIn && !form.checkOut && form.away.length === 0;

  return (
    <div className="space-y-6">
      {unusual && (
        <div className="flex gap-2 rounded-lg bg-warning/10 p-3 text-xs text-warning">
          <TriangleAlert size={14} className="mt-px shrink-0" />
          The recorded punches are out of the usual order, so they can’t be shown here. Enter the day as it should be.
        </div>
      )}

      <section>
        <p className="eyebrow mb-2">Quick fill</p>
        <div className={`grid gap-2 ${presets.length === 3 ? "grid-cols-3" : "grid-cols-2"}`}>
          {presets.map(({ label, detail, icon: Icon, form: preset }) => (
            <button
              key={label} type="button"
              className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left transition-colors hover:border-brand-500/50 hover:bg-brand-500/[0.04]"
              onClick={() => setForm(preset)}
            >
              <span className="flex items-center gap-1.5 text-[13px] font-medium text-fg"><Icon size={14} className="text-fg-subtle" />{label}</span>
              <span className="mt-0.5 block text-[11px] tabular-nums text-fg-subtle">{detail}</span>
            </button>
          ))}
        </div>
      </section>

      <section>
        <p className="eyebrow mb-2">Working time</p>
        <div className="grid grid-cols-2 gap-3">
          <TimeField id="edit-in" label="Check in" value={form.checkIn} nextDay={built.nextDay.has("checkIn")}
            onChange={(v) => setForm((f) => ({ ...f, checkIn: v }))} />
          <TimeField id="edit-out" label="Check out" value={form.checkOut} nextDay={built.nextDay.has("checkOut")} clearable
            hint={form.checkIn && !form.checkOut ? "Leave empty if they haven’t checked out." : undefined}
            onChange={(v) => setForm((f) => ({ ...f, checkOut: v }))} />
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <p className="eyebrow">Time away</p>
          <div className="flex gap-1">
            <button type="button" className="btn-ghost btn-sm" onClick={() => addAway("BREAK")} disabled={!form.checkIn}>
              <Plus size={13} /> Add break
            </button>
            <button type="button" className="btn-ghost btn-sm" onClick={() => addAway("OUT")} disabled={!form.checkIn}>
              <Plus size={13} /> Add time out
            </button>
          </div>
        </div>
        {form.away.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line px-3 py-3 text-xs text-fg-subtle">
            No breaks — all the time between check-in and check-out counts as worked.
          </p>
        ) : (
          <ul className="space-y-2">
            {form.away.map((r) => (
              <li key={r.key} className="grid grid-cols-[7.5rem_1fr_auto_1fr_auto] items-center gap-2">
                <select className="input" aria-label="Kind of time away" value={r.kind} onChange={(e) => setAway(r.key, { kind: e.target.value as AwayKind })}>
                  <option value="BREAK">Break</option>
                  <option value="OUT">Time out</option>
                </select>
                <input type="time" className="input tabular-nums" aria-label="From" value={r.from} onChange={(e) => setAway(r.key, { from: e.target.value })} />
                <span className="text-fg-subtle">–</span>
                <input type="time" className="input tabular-nums" aria-label="To" value={r.to} onChange={(e) => setAway(r.key, { to: e.target.value })} />
                <button type="button" className="btn-icon text-fg-subtle hover:text-danger" aria-label="Remove"
                  onClick={() => setForm((f) => ({ ...f, away: f.away.filter((x) => x.key !== r.key) }))}>
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={`rounded-xl border p-4 ${built.problems.length ? "border-danger/30 bg-danger/[0.04]" : "border-line bg-panel"}`}>
        <p className="eyebrow mb-2">Result</p>
        {built.problems.length > 0 ? (
          <ul className="space-y-1 text-[13px] text-danger">
            {built.problems.map((p) => <li key={p} className="flex gap-1.5"><TriangleAlert size={14} className="mt-0.5 shrink-0" />{p}</li>)}
          </ul>
        ) : absent ? (
          <p className="flex items-center gap-2 text-[13px] text-fg"><StatusBadge status="ABSENT" /> The day will be recorded as absent.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={result.status} />
              {result.late > 0 && <span className="badge badge-warning">{fmtMins(result.late)} late</span>}
              {result.early > 0 && <span className="badge badge-warning">{fmtMins(result.early)} early</span>}
              {result.extra > 0 && <span className="badge badge-info">{fmtMins(result.extra)} beyond shift</span>}
            </div>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-[13px]">
              {[
                ["Total", built.open ? "—" : fmtMins(built.total, "0m")],
                ["Away", fmtMins(built.away, "None")],
                ["Worked", built.open ? "Still in" : fmtMins(built.worked, "0m")],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-[11px] text-fg-subtle">{label}</dt>
                  <dd className="font-semibold tabular-nums text-fg">{value}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
        {built.problems.length === 0 && built.warnings.map((w) => (
          <p key={w} className="mt-2 flex gap-1.5 text-xs text-warning"><Info size={13} className="mt-px shrink-0" />{w}</p>
        ))}
      </section>

      <section>
        <label className="label" htmlFor="edit-reason">Reason for the change</label>
        <div className="mb-2 flex flex-wrap gap-1.5">
          {REASONS.map((r) => (
            <button key={r} type="button"
              className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${reason === r ? "border-brand-500 bg-brand-500/10 text-fg" : "border-line text-fg-muted hover:border-line-strong hover:text-fg"}`}
              onClick={() => setReason(r)}>
              {r}
            </button>
          ))}
        </div>
        <textarea
          id="edit-reason" className="input min-h-16" maxLength={255} value={reason}
          placeholder="Or write your own…" onChange={(e) => setReason(e.target.value)}
        />
        <p className="hint">Saved straight away — no approval needed. The employee sees this reason, and the old punches stay in the history.</p>
      </section>
    </div>
  );
}

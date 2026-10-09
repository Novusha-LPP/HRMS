/**
 * Pure helpers behind the attendance register: formatting, the day's time bar, and the simple
 * edit model (check-in, check-out, time away) converted to and from the raw punch list.
 */
import type { RegisterDay, RegisterPunch, RegisterPunchType } from "../../api/time";
import { clock12, nextDate, zonedParts, zonedToIso } from "../../lib/zonedTime";

export function fmtMins(m: number, empty = "—") {
  if (!m || m <= 0) return empty;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return h ? (r ? `${h}h ${r}m` : `${h}h`) : `${r}m`;
}

/** "09:30 AM", with "+1" when the instant falls on the next calendar day. */
export function punchTime(iso: string | null | undefined, day: RegisterDay) {
  if (!iso) return "—";
  return `${clock12(iso, day.timezone)}${zonedParts(iso, day.timezone).date !== day.work_date ? " +1" : ""}`;
}

export const hasWork = (d: RegisterDay) => !!d.first_punch_in;

const toMin = (hhmm: string) => +hhmm.slice(0, 2) * 60 + +hhmm.slice(3, 5);

// ─── Time bar ────────────────────────────────────────────────────────────────

export interface Segment { kind: "work" | "break" | "out" | "open"; from: number; to: number }

/**
 * Minutes from the day's local midnight for each stretch of the day: worked, on a break,
 * checked out in between, or still checked in (to `now`).
 */
export function daySegments(day: RegisterDay, now = new Date()): Segment[] {
  const base = new Date(zonedToIso(day.work_date, "00:00", day.timezone)).getTime();
  const at = (iso: string) => (new Date(iso).getTime() - base) / 60_000;
  const segments: Segment[] = [];
  let mark: number | null = null;
  let state: "work" | "break" | "out" | null = null;
  for (const p of day.punches) {
    const t = at(p.punched_at);
    if (mark !== null && state) segments.push({ kind: state, from: mark, to: t });
    state = p.punch_type === "IN" || p.punch_type === "BREAK_END" ? "work" : p.punch_type === "BREAK_START" ? "break" : "out";
    mark = t;
  }
  if (mark !== null && (state === "work" || state === "break")) {
    const end = Math.min(at(now.toISOString()), mark + 24 * 60);
    if (end > mark) segments.push({ kind: "open", from: mark, to: end });
  }
  return segments;
}

/** The shift as minutes from local midnight (an overnight shift ends after 1440). */
export function shiftWindow(day: RegisterDay) {
  const from = toMin(day.shift_start);
  let to = toMin(day.shift_end);
  if (to <= from) to += 24 * 60;
  return { from, to };
}

/** One axis for a set of days: the shift with room either side, widened to fit every punch. */
export function timelineRange(days: RegisterDay[]) {
  let from = Infinity;
  let to = -Infinity;
  for (const d of days) {
    const s = shiftWindow(d);
    from = Math.min(from, s.from - 120);
    to = Math.max(to, s.to + 180);
    for (const seg of daySegments(d)) {
      from = Math.min(from, seg.from);
      to = Math.max(to, seg.to);
    }
  }
  if (!Number.isFinite(from)) return { from: 6 * 60, to: 23 * 60 };
  return { from: Math.max(-6 * 60, Math.floor(from / 60) * 60), to: Math.min(48 * 60, Math.ceil(to / 60) * 60) };
}

// ─── Simple edit model ───────────────────────────────────────────────────────

export type AwayKind = "BREAK" | "OUT";
export interface AwayRow { key: string; kind: AwayKind; from: string; to: string }
export interface DayForm { checkIn: string; checkOut: string; away: AwayRow[] }

let seq = 0;
export const rowKey = () => `away-${++seq}`;

/** The punches as check-in / check-out / time away, or null when they don't fit that shape. */
export function formFromPunches(day: RegisterDay): DayForm | null {
  const p = day.punches;
  const time = (x: RegisterPunch) => zonedParts(x.punched_at, day.timezone).time;
  if (p.length === 0) return { checkIn: "", checkOut: "", away: [] };
  if (p[0].punch_type !== "IN") return null;
  const form: DayForm = { checkIn: time(p[0]), checkOut: "", away: [] };
  for (let i = 1; i < p.length; i++) {
    const cur = p[i];
    const next = p[i + 1];
    if (cur.punch_type === "BREAK_START") {
      if (next?.punch_type === "BREAK_END") { form.away.push({ key: rowKey(), kind: "BREAK", from: time(cur), to: time(next) }); i++; }
      else form.away.push({ key: rowKey(), kind: "BREAK", from: time(cur), to: "" });
    } else if (cur.punch_type === "OUT") {
      if (!next) form.checkOut = time(cur);
      else if (next.punch_type === "IN") { form.away.push({ key: rowKey(), kind: "OUT", from: time(cur), to: time(next) }); i++; }
      else return null;
    } else return null;
  }
  return form;
}

export interface Built {
  punches: { punch_type: RegisterPunchType; punched_at: string }[];
  problems: string[];
  warnings: string[];
  checkInIso?: string;
  checkOutIso?: string;
  total: number;
  away: number;
  worked: number;
  open: boolean;
  /** Times that fall on the next calendar day, for the "next day" hints. */
  nextDay: Set<string>;
}

/**
 * Turn the form into the day's punch list. A time earlier than the check-in is read as the next
 * day (a check-out after midnight); on a night shift an early-morning check-in is too.
 */
export function buildPunches(form: DayForm, day: RegisterDay): Built {
  const problems: string[] = [];
  const warnings: string[] = [];
  const nextDay = new Set<string>();
  const empty: Built = { punches: [], problems, warnings, total: 0, away: 0, worked: 0, open: false, nextDay };
  if (!form.checkIn) {
    if (form.checkOut || form.away.length) problems.push("Enter the check-in time.");
    return empty;
  }
  const { from: shiftFrom, to: shiftTo } = shiftWindow(day);
  const overnight = shiftTo > 24 * 60;
  const boundary = overnight ? (shiftFrom + shiftTo - 24 * 60) / 2 : -1;
  const inDate = overnight && toMin(form.checkIn) < boundary ? nextDate(day.work_date) : day.work_date;
  if (inDate !== day.work_date) nextDay.add("checkIn");
  const ciMin = toMin(form.checkIn);
  // An instant for a time on or after the check-in (next day when the clock reads earlier).
  const after = (hhmm: string, field: string) => {
    const date = toMin(hhmm) < ciMin ? nextDate(inDate) : inDate;
    if (date !== day.work_date) nextDay.add(field);
    return zonedToIso(date, hhmm, day.timezone);
  };
  const ci = zonedToIso(inDate, form.checkIn, day.timezone);
  const co = form.checkOut ? after(form.checkOut, "checkOut") : undefined;
  const ms = (iso: string) => new Date(iso).getTime();
  if (co && ms(co) === ms(ci)) problems.push("Check-out can't be at the same time as check-in.");

  const away = form.away
    .map((r) => {
      if (!r.from || !r.to) {
        problems.push(`${r.kind === "BREAK" ? "Break" : "Time out"} ${r.from || "…"}–${r.to || "…"} needs both times.`);
        return null;
      }
      const from = after(r.from, `${r.key}-from`);
      let to = after(r.to, `${r.key}-to`);
      if (ms(to) <= ms(from)) to = zonedToIso(nextDate(zonedParts(from, day.timezone).date), r.to, day.timezone);
      return { ...r, fromIso: from, toIso: to };
    })
    .filter((r): r is NonNullable<typeof r> => !!r)
    .sort((a, b) => ms(a.fromIso) - ms(b.fromIso));

  for (let i = 0; i < away.length; i++) {
    const r = away[i];
    if (ms(r.fromIso) <= ms(ci) || (co && ms(r.toIso) >= ms(co))) {
      problems.push(`${r.kind === "BREAK" ? "Break" : "Time out"} ${r.from}–${r.to} must be between check-in and check-out.`);
    }
    if (i && ms(r.fromIso) < ms(away[i - 1].toIso)) problems.push(`${r.from}–${r.to} overlaps ${away[i - 1].from}–${away[i - 1].to}.`);
  }

  const punches: Built["punches"] = [{ punch_type: "IN", punched_at: ci }];
  for (const r of away) {
    punches.push(
      { punch_type: r.kind === "BREAK" ? "BREAK_START" : "OUT", punched_at: r.fromIso },
      { punch_type: r.kind === "BREAK" ? "BREAK_END" : "IN", punched_at: r.toIso },
    );
  }
  if (co) punches.push({ punch_type: "OUT", punched_at: co });

  const awayMin = away.reduce((s, r) => s + (ms(r.toIso) - ms(r.fromIso)) / 60_000, 0);
  const total = co ? (ms(co) - ms(ci)) / 60_000 : 0;
  if (!co) warnings.push("No check-out: the day stays open, and becomes a missed punch 24 hours after check-in.");
  if (total > 16 * 60) warnings.push("Over 16 hours — make sure the check-out is right.");
  return {
    punches, problems: [...new Set(problems)], warnings, checkInIso: ci, checkOutIso: co,
    total: Math.round(total), away: Math.round(awayMin), worked: Math.max(0, Math.round(total - awayMin)), open: !co, nextDay,
  };
}

/** Send untouched punches back exactly as stored (seconds and all), so they aren't re-recorded. */
export function keepOriginals(built: Built["punches"], day: RegisterDay) {
  const pool = new Map<string, string[]>();
  for (const p of day.punches) {
    const { date, time } = zonedParts(p.punched_at, day.timezone);
    const key = `${p.punch_type}|${date}|${time}`;
    pool.set(key, [...(pool.get(key) ?? []), p.punched_at]);
  }
  return built.map((p) => {
    const { date, time } = zonedParts(p.punched_at, day.timezone);
    const original = pool.get(`${p.punch_type}|${date}|${time}`)?.shift();
    return original ? { ...p, punched_at: original } : p;
  });
}

/** What the day should come out as — the server has the final word (rounding, overtime rules). */
export function expectedResult(b: Built, day: RegisterDay) {
  if (!b.checkInIso) return { status: "ABSENT", late: 0, early: 0, extra: 0 };
  if (day.is_off_day) return { status: "OFF_DAY_WORKED", late: 0, early: 0, extra: b.open ? 0 : b.worked };
  const { from, to } = shiftWindow(day);
  const midnight = new Date(zonedToIso(day.work_date, "00:00", day.timezone)).getTime();
  const at = (iso: string) => (new Date(iso).getTime() - midnight) / 60_000;
  const late = Math.max(0, Math.floor(at(b.checkInIso) - from) - day.grace_late_minutes);
  const early = b.checkOutIso ? Math.max(0, Math.floor(to - at(b.checkOutIso)) - day.grace_early_minutes) : 0;
  const extra = b.open ? 0 : Math.max(0, b.worked - (to - from));
  let status = "PRESENT";
  if (b.open) status = late ? "LATE" : "PRESENT";
  else if (b.worked < day.half_day_minutes) status = "HALF_DAY";
  else if (late) status = "LATE";
  else if (early) status = "EARLY_DEPARTURE";
  return { status, late, early, extra };
}

export const PUNCH_LABEL: Record<string, string> = {
  IN: "Checked in", OUT: "Checked out", BREAK_START: "Break started", BREAK_END: "Break ended",
};

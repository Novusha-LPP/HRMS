/**
 * How a direct report's day reads on the My team page and the manager dashboard: one bucket
 * per person (for the filters and counts) plus the badge to show.
 */
import type { TeamMember } from "../../api/dashboard";
import { clock12 } from "../../lib/zonedTime";

export type TeamBucket = "in" | "out" | "not_in" | "leave" | "off";

export const BUCKET_LABEL: Record<TeamBucket, string> = {
  in: "Checked in",
  out: "Checked out",
  not_in: "Not checked in",
  leave: "On leave",
  off: "Day off",
};

type Tone = "success" | "warning" | "danger" | "info" | "plum" | "neutral";

export interface MemberState {
  bucket: TeamBucket;
  label: string;
  tone: Tone;
  late: boolean;
  /** "09:32 AM", on the member's policy clock. */
  firstIn: string | null;
  lastOut: string | null;
}

export function memberState(m: TeamMember): MemberState {
  const t = m.today;
  if (!t) return { bucket: "off", label: "Not joined yet", tone: "neutral", late: false, firstIn: null, lastOut: null };
  const firstIn = t.first_punch_in ? clock12(t.first_punch_in, t.timezone) : null;
  const lastOut = t.last_punch_out ? clock12(t.last_punch_out, t.timezone) : null;
  const late = t.late_by_minutes > 0 || t.status === "LATE";
  if (t.is_checked_in) return { bucket: "in", label: "Checked in", tone: "success", late, firstIn, lastOut: null };
  if (t.first_punch_in) {
    return { bucket: "out", label: t.status === "HALF_DAY" ? "Half day" : "Checked out", tone: t.status === "HALF_DAY" ? "warning" : "neutral", late, firstIn, lastOut };
  }
  if (t.status === "ON_LEAVE") return { bucket: "leave", label: t.leave_type ? `On leave · ${t.leave_type}` : "On leave", tone: "info", late: false, firstIn, lastOut };
  if (t.status === "HOLIDAY") return { bucket: "off", label: t.holiday_name ?? "Holiday", tone: "plum", late: false, firstIn, lastOut };
  if (t.status === "WEEKEND") return { bucket: "off", label: "Week off", tone: "neutral", late: false, firstIn, lastOut };
  return { bucket: "not_in", label: t.status === "MISSED_PUNCH" ? "Missed punch" : "Not checked in", tone: "warning", late: false, firstIn, lastOut };
}

/** People at work today: checked in now, or came in and already left. */
export const atWork = (s: MemberState) => s.bucket === "in" || s.bucket === "out";

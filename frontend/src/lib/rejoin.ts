/** Wording and checks for rejoining, leaving and the hire-time duplicate warning. */
import type { Employment, RejoinChoice, RejoinMode, SeparationAction, SeparationPreview } from "../api/people";

export const MODE_LABEL: Record<RejoinMode, string> = {
  CONTINUE: "Continue earlier service",
  FRESH: "Start fresh",
};

export const MODE_HELP: Record<RejoinMode, string> = {
  CONTINUE: "Their earlier service counts and any leave still held is restored. Leave that was paid out or lapsed when they left stays gone.",
  FRESH: "Service for leave starts again from the rejoin date and any unused leave lapses.",
};

/** "42 days", "1 day", or a note when the dates are not known yet. */
export function describeGap(days: number | null): string {
  if (days === null) return "Unknown";
  if (days < 0) return "Before they left";
  if (days === 0) return "Same day";
  return `${days} ${days === 1 ? "day" : "days"}`;
}

export function days(n: number): string {
  return `${n % 1 === 0 ? n : n.toFixed(1)} ${n === 1 ? "day" : "days"}`;
}

/** What the rejoin form sends. Empty text and unticked boxes are left out so the company default applies. */
export function buildRejoinChoice(input: {
  mode: RejoinMode | "";
  condoned: boolean;
  reason: string;
  gratuityPaid: boolean;
}): RejoinChoice {
  const choice: RejoinChoice = {};
  if (input.mode) choice.mode = input.mode;
  if (input.condoned) choice.break_condoned = true;
  if (input.reason.trim()) choice.reason = input.reason.trim();
  if (input.gratuityPaid) choice.gratuity_paid_at_exit = true;
  return choice;
}

/** One line per unused balance that a separation would settle. */
export function describeSettlement(item: SeparationPreview["items"][number]): string {
  const parts: string[] = [];
  if (item.encash_days > 0) parts.push(`${days(item.encash_days)} paid out`);
  if (item.lapse_days > 0) parts.push(`${days(item.lapse_days)} lapses`);
  if (item.held_days > 0) {
    parts.push(
      item.hold_expires_on
        ? `${days(item.held_days)} held until ${item.hold_expires_on}`
        : `${days(item.held_days)} held`,
    );
  }
  return parts.join(", ");
}

export const ACTION_LABEL: Record<SeparationAction, string> = {
  LAPSE: "Lapse",
  ENCASH: "Pay out",
  HOLD: "Hold",
};

const norm = (s: string | null | undefined) => (s ?? "").trim().toLowerCase().replace(/\s+/g, " ");

/**
 * People the new hire might already be: same first and last name, and the same birth date when
 * both are known. A name alone is a match too (many people lack a recorded birth date), so the
 * warning asks HR rather than blocking them.
 */
export function findPossibleDuplicates(
  people: Pick<Employment, "id" | "first_name" | "last_name" | "full_name" | "employee_number" | "employment_state" | "date_of_birth">[],
  candidate: { first: string; last: string; dob: string },
) {
  const first = norm(candidate.first);
  const last = norm(candidate.last);
  if (!first || !last) return [];
  return people.filter((p) => {
    const pf = norm(p.first_name) || norm(p.full_name).split(" ")[0] || "";
    const pl = norm(p.last_name) || norm(p.full_name).split(" ").slice(1).join(" ");
    if (pf !== first || pl !== last) return false;
    if (candidate.dob && p.date_of_birth && candidate.dob !== p.date_of_birth) return false;
    return true;
  });
}

import type { ReminderFrequency, ReminderRuleInput, ReminderTrigger } from "../api/reminders";

/** What HR sees for each event, in plain words. */
export const TRIGGERS: Record<ReminderTrigger, { label: string; short: string; help: string; oneOff: boolean }> = {
  BIRTHDAY: { label: "Birthday", short: "birthday", help: "Every year, from the date of birth on the employee’s record.", oneOff: false },
  WORK_ANNIVERSARY: { label: "Work anniversary", short: "work anniversary", help: "Every year, counted from the joining date.", oneOff: false },
  NEW_JOINER: { label: "New joiner", short: "joining day", help: "Once, from the joining date: get desks, laptops and accounts ready.", oneOff: true },
  EXIT: { label: "Exit", short: "last working day", help: "Once, from the last working day: handover, assets and settlement.", oneOff: true },
};

export const FREQUENCIES: Record<ReminderFrequency, { label: string; help: string }> = {
  SAME_DAY: { label: "On the day", help: "One mail, on the day itself." },
  ONE_DAY_BEFORE: { label: "The day before", help: "One mail, the day before." },
  CONTINUOUS: { label: "Every day", help: "A mail every day, starting a few days ahead, until the day." },
  ALTERNATE_DAYS: { label: "Every other day", help: "A mail every second day, starting a few days ahead, and on the day." },
  CUSTOM: { label: "Days I choose", help: "Pick exactly which days, such as 7, 3, 1 and the day." },
};

/** How many days before the day each mail goes out (0 is the day itself), latest-first order reversed to earliest-first. */
export function offsetsFor(frequency: ReminderFrequency, daysBefore: number, custom: number[]): number[] {
  const days = Math.max(0, Math.floor(daysBefore) || 0);
  let out: number[];
  switch (frequency) {
    case "SAME_DAY": out = [0]; break;
    case "ONE_DAY_BEFORE": out = [1]; break;
    case "CONTINUOUS": out = Array.from({ length: days + 1 }, (_, i) => i); break;
    case "ALTERNATE_DAYS": {
      const set = new Set<number>([0]);
      for (let d = days; d > 0; d -= 2) set.add(d);
      out = [...set];
      break;
    }
    default: out = custom.filter((d) => Number.isInteger(d) && d >= 0 && d <= 60);
  }
  return [...new Set(out)].sort((a, b) => b - a);
}

function joinList(parts: string[]): string {
  return parts.length <= 1 ? (parts[0] ?? "") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** "3 days before, 1 day before and on the birthday". */
export function describeOffsets(offsets: number[], noun: string): string {
  if (offsets.length === 0) return "on no day yet";
  const before = (n: number) => (n === 1 ? "1 day before" : `${n} days before`);
  const parts = offsets.map((n) => (n === 0 ? `on the ${noun}` : before(n)));
  return offsets.includes(0) ? joinList(parts) : `${joinList(parts)} the ${noun}`;
}

/** "09:00" → "9:00 AM". */
export function describeTime(time: string): string {
  const [h, m] = time.slice(0, 5).split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return time;
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

type Who = Pick<ReminderRuleInput, "notify_employee" | "notify_manager" | "notify_everyone"> & { extra_emails: string[] };

export function describeAudience(r: Who): string {
  const parts: string[] = [];
  if (r.notify_employee) parts.push("the person themselves");
  if (r.notify_manager) parts.push("their manager");
  if (r.notify_everyone) parts.push("everyone in the company");
  if (r.extra_emails.length) parts.push(r.extra_emails.length === 1 ? "1 other address" : `${r.extra_emails.length} other addresses`);
  return parts.length ? joinList(parts) : "nobody yet";
}

type Plan = Pick<ReminderRuleInput, "trigger" | "frequency" | "days_before" | "custom_offsets" | "send_time"> & Who;

/** The whole rule in one sentence, shown in the list and as the form's summary. */
export function describeRule(r: Plan): string {
  const when = TRIGGERS[r.trigger].short;
  const offsets = offsetsFor(r.frequency, r.days_before, r.custom_offsets);
  const greeting = r.notify_employee ? " The person’s own message is sent on the day only." : "";
  return `Email ${describeAudience(r)} ${describeOffsets(offsets, when)}, at ${describeTime(r.send_time)}.${greeting}`;
}

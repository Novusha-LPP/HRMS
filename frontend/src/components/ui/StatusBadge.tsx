type Tone = "success" | "warning" | "danger" | "info" | "plum" | "neutral" | "brand";

const TONE_BY_STATUS: Record<string, Tone> = {
  PRESENT: "success", APPROVED: "success", COMPLETED: "success", ACTIVE: "success", CONFIRMED: "success", VERIFIED: "success",
  LATE: "warning", PROBATION: "warning", HALF_DAY: "warning", PENDING: "warning", ACTION_REQUIRED: "warning",
  ABSENT: "danger", MISSED_PUNCH: "danger", REJECTED: "danger", OVERDUE: "danger", ON_NOTICE: "danger", NOTICE: "danger",
  ON_LEAVE: "info", IN_PROGRESS: "info", CONTRACT: "info", SUBMITTED: "info",
  HOLIDAY: "plum",
  WEEKEND: "neutral", SKIPPED: "neutral", CANCELLED: "neutral", SEPARATED: "neutral",
  INACTIVE: "neutral", DRAFT: "neutral", NOT_SUBMITTED: "neutral", CANCEL_REJECTED: "neutral",
};

export function statusTone(status: string): Tone {
  if (TONE_BY_STATUS[status]) return TONE_BY_STATUS[status];
  if (status.includes("PENDING")) return "warning";
  return "neutral";
}

export function humanize(status: string) {
  const level = status.match(/_L(\d)$/);
  const base = (level ? status.slice(0, -3) : status).toLowerCase().replace(/_/g, " ");
  const label = base.charAt(0).toUpperCase() + base.slice(1);
  return level ? `${label} · L${level[1]}` : label;
}

export const TONE_CLASS: Record<Tone, string> = {
  success: "badge badge-success",
  warning: "badge badge-warning",
  danger: "badge badge-danger",
  info: "badge badge-info",
  plum: "badge badge-plum",
  neutral: "badge badge-neutral",
  brand: "badge badge-brand",
};

export function StatusBadge({ status, label, tone, dot = true }: {
  status?: string;
  label?: string;
  tone?: Tone;
  dot?: boolean;
}) {
  const t = tone ?? statusTone(status ?? "");
  return (
    <span className={TONE_CLASS[t]}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />}
      {label ?? humanize(status ?? "")}
    </span>
  );
}

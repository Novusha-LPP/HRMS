import type {
  CandidateSource, EmploymentType, LinkType, OpeningReason, OpeningStatus, Priority, StageCategory, StageColor, WorkMode,
} from "../../api/recruitment";

type Tone = "success" | "warning" | "danger" | "info" | "plum" | "neutral" | "brand";

export const OPENING_STATUS: Record<OpeningStatus, { label: string; tone: Tone }> = {
  DRAFT: { label: "Draft", tone: "neutral" },
  PENDING_APPROVAL: { label: "Pending approval", tone: "warning" },
  REJECTED: { label: "Rejected", tone: "danger" },
  OPEN: { label: "Open", tone: "success" },
  ON_HOLD: { label: "On hold", tone: "plum" },
  FILLED: { label: "Filled", tone: "info" },
  CLOSED: { label: "Closed", tone: "neutral" },
};

export const PRIORITY: Record<Priority, { label: string; tone: Tone }> = {
  LOW: { label: "Low", tone: "neutral" },
  MEDIUM: { label: "Medium", tone: "info" },
  HIGH: { label: "High", tone: "warning" },
  CRITICAL: { label: "Critical", tone: "danger" },
};

export const EMPLOYMENT_TYPES: Record<EmploymentType, string> = {
  FULL_TIME: "Full-time",
  PART_TIME: "Part-time",
  CONTRACT: "Contract",
  INTERN: "Internship",
  CONSULTANT: "Consultant",
};

export const WORK_MODES: Record<WorkMode, string> = { ONSITE: "On-site", HYBRID: "Hybrid", REMOTE: "Remote" };

export const REASONS: Record<OpeningReason, string> = {
  NEW_ROLE: "New role",
  REPLACEMENT: "Replacement",
  EXPANSION: "Team expansion",
};

export const SOURCES: Record<CandidateSource, string> = {
  REFERRAL: "Employee referral",
  LINKEDIN: "LinkedIn",
  JOB_PORTAL: "Job portal",
  CAREERS_SITE: "Careers site",
  AGENCY: "Recruitment agency",
  CAMPUS: "Campus",
  WALK_IN: "Walk-in",
  OTHER: "Other",
};

export const LINK_TYPES: Record<LinkType, string> = {
  LINKEDIN: "LinkedIn",
  GITHUB: "GitHub",
  PORTFOLIO: "Portfolio",
  WEBSITE: "Website",
  OTHER: "Other",
};

export const STAGE_CATEGORIES: Record<StageCategory, { label: string; hint: string }> = {
  ACTIVE: { label: "In progress", hint: "Still being evaluated" },
  HIRED: { label: "Hired", hint: "Fills a position; can become an employee" },
  REJECTED: { label: "Rejected", hint: "Turned down — needs a reason" },
  WITHDRAWN: { label: "Withdrawn", hint: "Candidate dropped out — needs a reason" },
};

export const STAGE_COLORS: StageColor[] = ["neutral", "brand", "info", "plum", "warning", "success", "danger"];

/** Dot / accent colour for a stage, from the shared semantic tokens. */
export const STAGE_DOT: Record<StageColor, string> = {
  neutral: "bg-fg-subtle",
  brand: "bg-brand-500",
  info: "bg-info",
  plum: "bg-plum",
  warning: "bg-warning",
  success: "bg-success",
  danger: "bg-danger",
};

export function money(value: string | number | null | undefined, currency = "INR") {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  try {
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : undefined, {
      style: "currency", currency, maximumFractionDigits: 0,
    }).format(n);
  } catch {
    return `${currency} ${n.toLocaleString()}`;
  }
}

export function range(min: string | null, max: string | null, fmt: (v: string) => string) {
  if (min && max) return min === max ? fmt(min) : `${fmt(min)} – ${fmt(max)}`;
  if (min) return `${fmt(min)}+`;
  if (max) return `Up to ${fmt(max)}`;
  return null;
}

export function years(v: string | number) {
  const n = Number(v);
  return `${Number.isInteger(n) ? n : n.toFixed(1)} yr${n === 1 ? "" : "s"}`;
}

export function daysSince(iso: string) {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  return days <= 0 ? "today" : days === 1 ? "1 day" : `${days} days`;
}

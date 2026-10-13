import type { AppStatus } from "../../api/integrations";

export function AppStatusBadge({ status }: { status: AppStatus }) {
  const tone = status === "ACTIVE" ? "badge-success" : status === "PAUSED" ? "badge-warning" : "badge-neutral";
  const label = status === "ACTIVE" ? "Active" : status === "PAUSED" ? "Paused" : "Disconnected";
  return <span className={`badge ${tone}`}>{label}</span>;
}

const OUTCOME_TONE: Record<string, string> = {
  CREATED: "badge-success",
  LINKED: "badge-success",
  UPDATED: "badge-info",
  APPLIED: "badge-info",
  SCHEDULED: "badge-info",
  ISSUED: "badge-neutral",
  NO_CHANGE: "badge-neutral",
  STALE_IGNORED: "badge-neutral",
  DRY_RUN: "badge-neutral",
  COMPLETED: "badge-neutral",
  HELD_FOR_REVIEW: "badge-warning",
  REJECTED: "badge-danger",
  FAILED: "badge-danger",
};

export function OutcomeBadge({ outcome }: { outcome: string }) {
  return (
    <span className={`badge ${OUTCOME_TONE[outcome] ?? "badge-neutral"}`}>
      {outcome.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}
    </span>
  );
}


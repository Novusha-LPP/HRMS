import { format, formatDistanceToNowStrict } from "date-fns";
import type { AppKind } from "../../api/integrations";

export const KIND_LABEL: Record<AppKind, string> = {
  TWO_WAY: "Two-way",
  RECEIVE_ONLY: "Receive only",
  READ_ONLY: "Read only",
};

export const KIND_HINT: Record<AppKind, string> = {
  TWO_WAY: "Sends employees to HRMS and reads changes back (an ERP or CRM).",
  RECEIVE_ONLY: "Only receives HRMS data (an LMS, a directory, a payroll vendor).",
  READ_ONLY: "Only reads data when it needs it (a BI tool or data warehouse).",
};

export function when(value: string | null | undefined) {
  if (!value) return "—";
  return format(new Date(value), "d MMM yyyy, HH:mm");
}

export function ago(value: string | null | undefined) {
  if (!value) return "never";
  return `${formatDistanceToNowStrict(new Date(value))} ago`;
}

export function fieldLabel(field: string, labels: Record<string, string>) {
  return labels[field] ?? field.replace(/_/g, " ");
}

export function humanizeEvent(event: string) {
  return event.replace("employee.", "").replace(/_/g, " ");
}

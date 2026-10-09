/** Personnel actions offered from an employee profile: labels, reasons and which states allow them. */

export type ActionKind =
  | "PROMOTION" | "CHANGE_JOB" | "CHANGE_MANAGER" | "CONFIRM" | "EXTEND_PROBATION"
  | "PLACE_ON_NOTICE" | "SEPARATION" | "REHIRE";

interface ActionMeta {
  menu: string;
  title: string;
  description: string;
  submit: string;
  success: string;
  dateLabel: string;
  /** Reason codes with their labels. Free text is always possible through "Other". */
  reasons: [string, string][];
  reasonRequired: boolean;
}

// Reason lists are defaults until HR can edit them in Settings → Masters (plan F2).
export const ACTION_META: Record<ActionKind, ActionMeta> = {
  PROMOTION: {
    menu: "Promote", title: "Promotion", submit: "Record promotion", success: "Promotion recorded",
    description: "A move to a higher designation, grade or position. Department, location and manager stay the same.",
    dateLabel: "Effective from",
    reasons: [["MERIT", "Performance / merit"], ["ANNUAL_REVIEW", "Annual review"], ["ROLE_EXPANSION", "Bigger role"], ["RESTRUCTURE", "Restructure"]],
    reasonRequired: false,
  },
  CHANGE_JOB: {
    menu: "Change designation", title: "Designation change", submit: "Change designation", success: "Designation changed",
    description: "A new job title that isn't a promotion, for example a role change at the same level.",
    dateLabel: "Effective from",
    reasons: [["ROLE_CHANGE", "Role change"], ["RESTRUCTURE", "Restructure"], ["CORRECTION", "Correcting the record"]],
    reasonRequired: false,
  },
  CHANGE_MANAGER: {
    menu: "Change manager", title: "Manager change", submit: "Change manager", success: "Manager changed",
    description: "Who this employee reports to. Their approvals route to the new manager from the effective date.",
    dateLabel: "Effective from",
    reasons: [["REORGANISATION", "Reorganisation"], ["MANAGER_LEFT", "Previous manager left"], ["TEAM_CHANGE", "Team change"]],
    reasonRequired: false,
  },
  CONFIRM: {
    menu: "Confirm", title: "Confirmation", submit: "Confirm employee", success: "Employee confirmed",
    description: "Ends probation. The employee becomes confirmed from this date.",
    dateLabel: "Confirmed from",
    reasons: [["PROBATION_COMPLETED", "Probation completed satisfactorily"], ["EARLY_CONFIRMATION", "Early confirmation"]],
    reasonRequired: false,
  },
  EXTEND_PROBATION: {
    menu: "Extend probation", title: "Probation extension", submit: "Extend probation", success: "Probation extended",
    description: "Keeps the employee on probation for longer. They stay on probation until you confirm them.",
    dateLabel: "Decided on",
    reasons: [["PERFORMANCE", "Performance needs improvement"], ["ATTENDANCE", "Attendance concerns"], ["MORE_TIME", "More time needed to assess"]],
    reasonRequired: true,
  },
  PLACE_ON_NOTICE: {
    menu: "Place on notice", title: "Notice period", submit: "Place on notice", success: "Notice period started",
    description: "Starts the notice period. Record the separation separately once the last working day is final.",
    dateLabel: "Notice starts on",
    reasons: [["RESIGNATION", "Resignation"], ["TERMINATION", "Termination"], ["RETIREMENT", "Retirement"], ["END_OF_CONTRACT", "End of contract"]],
    reasonRequired: true,
  },
  SEPARATION: {
    menu: "Record separation", title: "Separation", submit: "Record separation", success: "Separation recorded",
    description: "Ends the employment after the last working day.",
    dateLabel: "Last working day",
    reasons: [["RESIGNATION", "Resignation"], ["TERMINATION", "Termination"], ["RETIREMENT", "Retirement"], ["END_OF_CONTRACT", "End of contract"], ["ABSCONDING", "Absconding"], ["DEATH", "Death"]],
    reasonRequired: true,
  },
  REHIRE: {
    menu: "Rehire", title: "Rehire", submit: "Rehire employee", success: "Employee rehired",
    description: "Brings a former employee back on the same record. Their earlier history is kept, and they start on probation.",
    dateLabel: "Rejoins on",
    reasons: [["REJOINING", "Rejoining"], ["SEASONAL_RETURN", "Seasonal return"]],
    reasonRequired: false,
  },
};

const ALL_REASON_LABELS = new Map(Object.values(ACTION_META).flatMap((m) => m.reasons));

/** The label HR chose for a stored reason code, or the free text itself. */
export function reasonLabel(code: string | null | undefined) {
  if (!code) return null;
  return ALL_REASON_LABELS.get(code) ?? code;
}

/** Which actions make sense for an employee in this state (the API enforces the same rules). */
export function actionsFor(state: string, placed: boolean): ActionKind[] {
  if (state === "SEPARATED") return ["REHIRE"];
  const list: ActionKind[] = [];
  if (state === "PROBATION") list.push("CONFIRM", "EXTEND_PROBATION");
  if (placed) list.push("PROMOTION", "CHANGE_JOB", "CHANGE_MANAGER");
  if (state === "ACTIVE" || state === "PROBATION" || state === "ON_HOLD") list.push("PLACE_ON_NOTICE");
  list.push("SEPARATION");
  return list;
}

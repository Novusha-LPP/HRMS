import { api, API_BASE_URL, ApiError, type Versioned } from "./client";

export interface Employment {
  id: string;
  person_id: string;
  legal_entity_id: string;
  employee_number: string;
  first_name?: string | null;
  last_name?: string | null;
  full_name?: string | null;
  email?: string | null;
  role?: string | null;
  hire_date: string;
  separation_date: string | null;
  employment_state: string;
  service_stage: string | null;
  version: number;
  date_of_birth: string | null;
  gender: string | null;
  // Populated from the employee's current (open) assignment — null until a
  // HIRE personnel action has actually placed them (see personnelActionsApi).
  legal_entity_name: string | null;
  org_unit_id: string | null;
  department: string | null;
  team_name?: string | null;
  job_id: string | null;
  designation: string | null;
  grade_id?: string | null;
  grade?: string | null;
  position_id?: string | null;
  position_title?: string | null;
  location_id: string | null;
  location: string | null;
  manager_employment_id: string | null;
  manager_name: string | null;
}

export interface Person {
  id: string;
  legal_first_name: string;
  legal_last_name: string;
  preferred_name: string | null;
  date_of_birth: string | null;
  gender: string | null;
  version: number;
}

export interface MyProfile {
  id: string;
  legal_first_name: string;
  legal_last_name: string;
  preferred_name: string | null;
  date_of_birth: string | null;
  gender: string | null;
  nationality: string | null;
  email: string | null;
  mobile: string | null;
  version: number;
}

export type PersonnelActionType =
  | "HIRE" | "REHIRE" | "TRANSFER" | "PROMOTION" | "DEMOTION" | "CONFIRM"
  | "EXTEND_PROBATION" | "PLACE_ON_NOTICE" | "SEPARATION" | "CHANGE_MANAGER"
  | "CHANGE_GRADE" | "CHANGE_COST_CENTRE" | "CHANGE_JOB";

export interface PersonnelActionChanges {
  org_unit_id?: string;
  location_id?: string;
  job_id?: string;
  grade_id?: string;
  position_id?: string;
  cost_centre_id?: string;
  manager_employment_id?: string;
  /** Informational dates recorded with status actions (not placements). */
  probation_extended_until?: string;
  expected_last_working_day?: string;
  last_working_day?: string;
  note?: string;
}

export interface PersonnelAction {
  id: string;
  employment_id: string;
  type: PersonnelActionType;
  reason_code: string | null;
  effective_date: string;
  status: string;
  changes: PersonnelActionChanges | null;
  version: number;
}

export interface PersonnelActionListItem {
  id: string;
  type: PersonnelActionType;
  effective_date: string;
  status: string;
  submitted_at: string | null;
  failure_reason?: string | null;
  reason_code?: string | null;
  changes?: PersonnelActionChanges | null;
}

// The list endpoints cap a single response at 200 rows. A group with more people
// than that (a large tenant, or several companies together) would otherwise be
// silently truncated, so walk the pages until one comes back short.
const PAGE = 200;
async function fetchAll<T>(page: (offset: number) => Promise<T[]>): Promise<T[]> {
  const all: T[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const rows = await page(offset);
    all.push(...rows);
    if (rows.length < PAGE) return all;
  }
}

export const peopleApi = {
  listEmployees: (status?: string, limit = 50, offset = 0) => {
    const q = status ? `?filter[status]=${status}&limit=${limit}&offset=${offset}` : `?limit=${limit}&offset=${offset}`;
    return api.get<Employment[]>(`/v1/employees${q}`);
  },
  listAllEmployees: () => fetchAll((offset) => peopleApi.listEmployees(undefined, PAGE, offset)),
  getEmployee: (id: string) => api.get<Employment>(`/v1/employees/${id}`),
  listPersons: (limit = 200, offset = 0) => api.get<Person[]>(`/v1/persons?limit=${limit}&offset=${offset}`),
  listAllPersons: () => fetchAll((offset) => peopleApi.listPersons(PAGE, offset)),
  createPerson: (body: {
    legal_first_name: string;
    legal_last_name: string;
    preferred_name?: string;
    date_of_birth?: string | null;
    gender?: string | null;
  }) =>
    api.post<Person>("/v1/persons", body),
  createEmployment: (body: {
    person_id: string;
    legal_entity_id: string;
    employee_number?: string;
    hire_date: string;
    /** The person already has an earlier employment and this really is a separate, new one. */
    confirm_new_employment?: boolean;
  }) =>
    api.post<Employment>("/v1/employees", body),
  getMyProfile: () => api.get<MyProfile>("/v1/persons/me"),
  updateMyProfile: (body: {
    preferred_name?: string | null;
    date_of_birth?: string | null;
    gender?: string | null;
    nationality?: string | null;
    mobile?: string | null;
  } & Versioned) => api.patch<MyProfile>("/v1/persons/me", body),
};

export const personnelActionsApi = {
  create: (body: {
    employment_id: string;
    type: PersonnelActionType;
    effective_date: string;
    reason_code?: string;
    changes?: PersonnelActionChanges;
    /** Why HR is changing a field a connected app (e.g. the ERP) owns for this employee. */
    override_reason?: string;
    /** Only for REHIRE: continue earlier service and leave, or start fresh. */
    rejoin?: RejoinChoice;
  }) => api.post<PersonnelAction>("/v1/personnel-actions", body),
  list: (employmentId: string) =>
    api.get<PersonnelActionListItem[]>(`/v1/personnel-actions?employment_id=${employmentId}`),
  cancel: (actionId: string) => api.post<PersonnelAction>(`/v1/personnel-actions/${actionId}/cancel`, {}),
};

export type RejoinMode = "CONTINUE" | "FRESH";

export interface RejoinChoice {
  mode?: RejoinMode;
  break_condoned?: boolean;
  reason?: string;
  gratuity_paid_at_exit?: boolean;
}

export interface RejoinPreview {
  employment_id: string;
  left_on: string | null;
  rejoin_on: string;
  gap_days: number | null;
  mode: RejoinMode;
  default_mode: RejoinMode;
  allowed_modes: RejoinMode[];
  force_fresh_after_days: number | null;
  gratuity_paid: boolean | null;
  automatic: boolean;
  reason: string | null;
  can_proceed: boolean;
  blocked: string[];
  notes: string[];
  leave: { leave_type_id: string; leave_type_name: string; days: number; outcome: "KEPT" | "LAPSE" }[];
}

export interface RejoinPolicy {
  id: string;
  legal_entity_id: string | null;
  default_mode: RejoinMode;
  force_fresh_after_days: number | null;
  effective_from: string;
}

export interface EmploymentSpell {
  spell_no: number;
  joined_on: string;
  left_on: string | null;
  exit_reason: string | null;
  gratuity_paid: boolean | null;
  rejoin: { mode: RejoinMode; break_start: string | null; break_end: string | null; break_condoned: boolean; reason: string | null } | null;
}

export interface EmploymentHistory {
  employment_id: string;
  hire_date: string;
  continuity_start_date: string | null;
  spells: EmploymentSpell[];
}

export interface PersonEmployment {
  employment_id: string;
  legal_entity_id: string;
  employee_number: string;
  employment_state: string;
  hire_date: string;
  separation_date: string | null;
  can_rejoin: boolean;
}

export type SeparationAction = "LAPSE" | "ENCASH" | "HOLD";

export interface SeparationRule {
  id: string;
  legal_entity_id: string | null;
  leave_type_id: string | null;
  on_separation: SeparationAction;
  hold_days: number | null;
  max_encash_days: number | null;
  effective_from: string;
}

export interface SeparationPreview {
  employment_id: string;
  as_of: string;
  items: {
    leave_type_id: string;
    leave_type_name: string;
    unused_days: number;
    action: SeparationAction;
    encash_days: number;
    lapse_days: number;
    held_days: number;
    hold_expires_on: string | null;
    note: string | null;
  }[];
}

export const rejoinApi = {
  preview: (employmentId: string, q: { effective_date: string; mode?: RejoinMode; break_condoned?: boolean; reason?: string; gratuity_paid_at_exit?: boolean }) => {
    const params = new URLSearchParams({ effective_date: q.effective_date });
    if (q.mode) params.set("mode", q.mode);
    if (q.break_condoned) params.set("break_condoned", "true");
    if (q.reason) params.set("reason", q.reason);
    if (q.gratuity_paid_at_exit !== undefined) params.set("gratuity_paid_at_exit", String(q.gratuity_paid_at_exit));
    return api.get<RejoinPreview>(`/v1/employees/${employmentId}/rejoin-preview?${params}`);
  },
  history: (employmentId: string) => api.get<EmploymentHistory>(`/v1/employees/${employmentId}/employment-history`),
  personEmployments: (personId: string) => api.get<PersonEmployment[]>(`/v1/persons/${personId}/employments`),
  listPolicies: () => api.get<RejoinPolicy[]>("/v1/people/rejoin-policies"),
  createPolicy: (body: { legal_entity_id?: string | null; default_mode: RejoinMode; force_fresh_after_days?: number | null; effective_from: string }) =>
    api.post<RejoinPolicy>("/v1/people/rejoin-policies", body),
  archivePolicy: (id: string) => api.delete<void>(`/v1/people/rejoin-policies/${id}`),
};

export const separationApi = {
  listRules: () => api.get<SeparationRule[]>("/v1/leave/separation-rules"),
  createRule: (body: { legal_entity_id?: string | null; leave_type_id?: string | null; on_separation: SeparationAction; hold_days?: number | null; max_encash_days?: number | null; effective_from: string }) =>
    api.post<SeparationRule>("/v1/leave/separation-rules", body),
  archiveRule: (id: string) => api.delete<void>(`/v1/leave/separation-rules/${id}`),
  preview: (employmentId: string, asOf: string) =>
    api.get<SeparationPreview>(`/v1/leave/separation-preview?employment_id=${employmentId}&as_of=${asOf}`),
};

export interface PriorServiceItem {
  id: string;
  employer_name: string;
  from_date: string;
  to_date: string;
  months: number;
  days: number;
  recognised_for_leave: boolean;
  recognised_for_gratuity: boolean;
  note: string | null;
}

export interface PriorServiceSummary {
  items: PriorServiceItem[];
  recognised_leave_months: number;
  recognised_gratuity_days: number;
}

export const priorServiceApi = {
  list: (personId: string) => api.get<PriorServiceSummary>(`/v1/persons/${personId}/prior-service`),
  add: (personId: string, body: { employer_name: string; from_date: string; to_date: string; recognised_for_leave: boolean; recognised_for_gratuity: boolean; note?: string }) =>
    api.post<PriorServiceItem>(`/v1/persons/${personId}/prior-service`, body),
  remove: (personId: string, id: string) => api.delete<void>(`/v1/persons/${personId}/prior-service/${id}`),
};

export interface CompanyTransferPreview {
  from_company: string;
  to_company: string;
  leave_mode: "CARRY" | "SETTLE";
  leave: { leave_type_id: string; leave_type_name: string; days: number }[];
  warnings: string[];
  blocked: string[];
  can_proceed: boolean;
}

export const companyTransferApi = {
  preview: (q: { employment_id: string; legal_entity_id: string; effective_date: string; leave_mode: "CARRY" | "SETTLE" }) =>
    api.get<CompanyTransferPreview>(`/v1/people/transfer-preview?${new URLSearchParams(q)}`),
  transfer: (body: {
    employment_id: string;
    legal_entity_id: string;
    effective_date: string;
    leave_mode: "CARRY" | "SETTLE";
    placement: { org_unit_id: string; location_id: string; job_id: string; manager_employment_id?: string };
    employee_number?: string;
    reason?: string;
  }) => api.post<{ from_employment_id: string; to_employment_id: string; employee_number: string; leave_mode: string }>("/v1/people/transfers", body),
};

export type LifecycleReportKind = "rejoins" | "company-transfers" | "separation-settlements";

export interface ReportTable {
  title: string;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  truncated: boolean;
}

const REPORT_PATH: Record<LifecycleReportKind, string> = {
  rejoins: "/v1/people/reports/rejoins",
  "company-transfers": "/v1/people/reports/company-transfers",
  "separation-settlements": "/v1/leave/reports/separation-settlements",
};

export const lifecycleReportsApi = {
  table: (kind: LifecycleReportKind, from: string, to: string) =>
    api.get<ReportTable>(`${REPORT_PATH[kind]}?from_date=${from}&to_date=${to}`),
  /** Download the same report as a spreadsheet file, with the session cookie. */
  async downloadCsv(kind: LifecycleReportKind, from: string, to: string) {
    const response = await fetch(`${API_BASE_URL}${REPORT_PATH[kind]}?from_date=${from}&to_date=${to}&format=csv`, {
      credentials: "include", headers: { "X-HRMS-Session": "cookie" }, signal: AbortSignal.timeout(60_000),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(response.status, body.code ?? "EXPORT_FAILED", typeof body.detail === "string" ? body.detail : "Couldn’t download the report");
    }
    const href = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = href;
    link.download = `${kind}-${to}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  },
};

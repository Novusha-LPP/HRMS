import { api, type Versioned } from "./client";

export type ReminderTrigger = "BIRTHDAY" | "WORK_ANNIVERSARY" | "NEW_JOINER" | "EXIT";
export type ReminderFrequency = "SAME_DAY" | "ONE_DAY_BEFORE" | "CONTINUOUS" | "ALTERNATE_DAYS" | "CUSTOM";
export type Audience = "EMPLOYEE" | "TEAM";

export interface ReminderRuleInput {
  name: string;
  trigger: ReminderTrigger;
  /** null: the whole group. */
  legal_entity_id: string | null;
  org_unit_id: string | null;
  frequency: ReminderFrequency;
  days_before: number;
  custom_offsets: number[];
  /** "HH:MM", in the company's timezone. */
  send_time: string;
  notify_employee: boolean;
  notify_manager: boolean;
  /** Also mail every employee with an email address, about everyone else. */
  notify_everyone: boolean;
  extra_emails: string[];
  digest: boolean;
  subject: string;
  body_html: string;
  employee_subject: string;
  employee_body_html: string;
  is_active: boolean;
}

export interface ReminderRule extends ReminderRuleInput {
  id: string;
  version: number;
  last_run_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface UpcomingPerson {
  full_name: string;
  department: string;
  event_date: string;
  days_left: number;
  sends_on: string[];
}

export interface ReminderDelivery {
  id: string;
  rule_id: string;
  send_date: string;
  audience: Audience;
  recipient_email: string;
  status: "PENDING" | "SENT" | "FAILED";
  attempts: number;
  sent_at: string | null;
  last_error: string | null;
}

export interface ReminderChange {
  action: string;
  changed_by: string;
  changed_at: string;
  changes: Record<string, { old: unknown; new: unknown }>;
}

export interface WordingPreview {
  subject: string;
  html: string;
  text: string;
  problems: string[];
}

export interface Starter {
  subject: string;
  body_html: string;
  employee_subject: string;
  employee_body_html: string;
}

const BASE = "/v1/reminders";

export const remindersApi = {
  list: () => api.get<ReminderRule[]>(`${BASE}/rules`),
  create: (body: ReminderRuleInput) => api.post<ReminderRule>(`${BASE}/rules`, body),
  update: (id: string, body: Partial<ReminderRuleInput> & Versioned) =>
    api.patch<ReminderRule>(`${BASE}/rules/${id}`, body),
  remove: (id: string) => api.delete<void>(`${BASE}/rules/${id}`),
  history: (id: string) => api.get<ReminderChange[]>(`${BASE}/rules/${id}/history`),
  upcoming: (id: string, days = 30) => api.get<UpcomingPerson[]>(`${BASE}/rules/${id}/upcoming?days=${days}`),
  testSend: (id: string, audience: Audience) =>
    api.post<{ sent_to: string }>(`${BASE}/rules/${id}/test-send?audience=${audience}`, {}),
  preview: (body: {
    trigger: ReminderTrigger;
    audience: Audience;
    subject: string;
    body_html: string;
    digest: boolean;
    legal_entity_id?: string | null;
  }) => api.post<WordingPreview>(`${BASE}/preview`, body),
  variables: (trigger: ReminderTrigger) =>
    api.get<{ variables: Record<string, string> }>(`${BASE}/variables?trigger=${trigger}`),
  defaults: (trigger: ReminderTrigger) => api.get<Starter>(`${BASE}/defaults?trigger=${trigger}`),
  deliveries: (ruleId?: string) =>
    api.get<ReminderDelivery[]>(`${BASE}/deliveries${ruleId ? `?rule_id=${ruleId}` : ""}`),
};

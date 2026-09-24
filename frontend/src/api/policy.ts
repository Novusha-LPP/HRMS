import { api } from "./client";

export interface PolicyTemplate {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  timezone: string;
  expected_start_time: string;
  expected_end_time: string;
  work_days: string;
  break_minutes: number;
  break_auto_deduct: boolean;
  grace_late_minutes: number;
  grace_early_departure_minutes: number;
  half_day_threshold_pct: number;
  ot_enabled: boolean;
  ot_qualifying_minutes: number;
  ot_rate: number;
  ot_daily_cap_minutes: number | null;
  punch_rounding_minutes: number;
  punch_rounding_direction: string;
  correction_requires_approval: boolean;
  correction_approval_levels: number;
  standard_minutes: number;
}

export interface EmployeePolicyAssignment {
  id: string;
  employment_id: string;
  policy_template_id: string;
  effective_from: string;
  effective_to: string | null;
  ot_qualifying_minutes_override: number | null;
  grace_late_minutes_override: number | null;
  grace_early_departure_minutes_override: number | null;
  ot_enabled_override: boolean | null;
  ot_rate_override: number | null;
  policy_template_name: string | null;
}

export const policyApi = {
  listTemplates: () => api.get<PolicyTemplate[]>("/v1/policies/templates"),
  getTemplate: (id: string) => api.get<PolicyTemplate>(`/v1/policies/templates/${id}`),
  createTemplate: (body: Partial<PolicyTemplate>) => api.post<PolicyTemplate>("/v1/policies/templates", body),
  updateTemplate: (id: string, body: Partial<PolicyTemplate>) => api.patch<PolicyTemplate>(`/v1/policies/templates/${id}`, body),
  deleteTemplate: (id: string) => api.delete(`/v1/policies/templates/${id}`),

  listAssignments: (employmentId?: string) => {
    const q = employmentId ? `?employment_id=${employmentId}` : "";
    return api.get<EmployeePolicyAssignment[]>(`/v1/policies/assignments${q}`);
  },
  assignPolicy: (body: Partial<EmployeePolicyAssignment>) => api.post<EmployeePolicyAssignment>("/v1/policies/assignments", body),
  removeAssignment: (id: string) => api.delete(`/v1/policies/assignments/${id}`),

  getEffectivePolicy: (employmentId: string, workDate?: string) => {
    const q = workDate ? `?work_date=${workDate}` : "";
    return api.get<PolicyTemplate & { work_date: string }>(`/v1/policies/employee/${employmentId}/effective${q}`);
  },
};

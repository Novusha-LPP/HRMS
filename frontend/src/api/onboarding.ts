import { api } from "./client";

export interface OnboardingItem {
  id: string;
  title: string;
  description: string | null;
  item_type: string;
  assignee_type: string;
  due_date: string | null;
  required: boolean;
  sequence: number;
  status: string;
  completed_at: string | null;
  notes: string | null;
}

export interface OnboardingCase {
  id: string;
  employment_id: string;
  template_id: string;
  status: string;
  hire_date: string;
  started_at: string;
  completed_at: string | null;
  items: OnboardingItem[];
  total_items: number;
  completed_items: number;
  overdue_items: number;
}

export type OnboardingItemType = "TASK" | "DOCUMENT" | "FORM" | "POLICY_ACK" | "IT_SETUP" | "TRAINING";
export type OnboardingAssignee = "HR" | "EMPLOYEE" | "IT" | "MANAGER";

export interface OnboardingTemplateItem {
  id?: string;
  title: string;
  description: string | null;
  item_type: OnboardingItemType;
  assignee_type: OnboardingAssignee;
  /** Days after the joining date; negative = before joining. */
  due_days_from_hire: number;
  required: boolean;
  sequence: number;
}

export interface OnboardingTemplate {
  id: string;
  name: string;
  description: string | null;
  trigger: string;
  is_default: boolean;
  status: string;
  items: OnboardingTemplateItem[];
}

export interface OnboardingTemplateInput {
  name: string;
  description?: string | null;
  is_default?: boolean;
  items: Omit<OnboardingTemplateItem, "id">[];
}

export const onboardingApi = {
  listTemplates: () => api.get<OnboardingTemplate[]>("/v1/onboarding/templates"),
  createTemplate: (body: OnboardingTemplateInput) => api.post<OnboardingTemplate>("/v1/onboarding/templates", body),
  /** Saves a new version; the old one is retired and started onboarding keeps its items. */
  replaceTemplate: (id: string, body: OnboardingTemplateInput) => api.put<OnboardingTemplate>(`/v1/onboarding/templates/${id}`, body),
  deactivateTemplate: (id: string) => api.post<OnboardingTemplate>(`/v1/onboarding/templates/${id}/deactivate`, {}),
  createStandardTemplate: () => api.post<OnboardingTemplate>("/v1/onboarding/templates/standard", {}),

  getCases: (employmentId?: string) => {
    const q = employmentId ? `?employment_id=${employmentId}` : "";
    return api.get<OnboardingCase[]>(`/v1/onboarding/cases${q}`);
  },

  getCase: (caseId: string) =>
    api.get<OnboardingCase>(`/v1/onboarding/cases/${caseId}`),

  updateItem: (itemId: string, status: string, notes?: string) =>
    api.patch<OnboardingItem>(`/v1/onboarding/items/${itemId}`, { status, notes }),

  createCase: (employmentId: string, hireDate: string, templateId?: string) =>
    api.post<OnboardingCase>("/v1/onboarding/cases", {
      employment_id: employmentId,
      hire_date: hireDate,
      template_id: templateId,
    }),
};

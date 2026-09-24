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

export const onboardingApi = {
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

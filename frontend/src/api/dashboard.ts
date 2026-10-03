import { api } from "./client";

export type LayoutDashboard = "hr" | "overview";

export type WidgetSize = "quarter" | "third" | "half" | "full";

export interface LayoutItem {
  widget: string;
  size: WidgetSize;
}

export interface WidgetInfo {
  id: string;
  title: string;
  description: string;
  category: string;
  default_size: WidgetSize;
  sizes: WidgetSize[];
}

export interface DashboardLayout {
  dashboard: string;
  widgets: LayoutItem[];
  /** True until the person saves their own arrangement. */
  is_default: boolean;
  /** The sections of /v1/dashboard/hr these widgets need, ready to pass to `hr()`. */
  sections: string;
  /** Every widget this person may place. */
  catalog: WidgetInfo[];
}

export const dashboardApi = {
  employee: (employmentId: string) =>
    api.get<Record<string, unknown>>(`/v1/dashboard/employee?employment_id=${employmentId}`),

  manager: (managerEmpId: string) =>
    api.get<Record<string, unknown>>(
      `/v1/dashboard/manager?manager_employment_id=${managerEmpId}`,
    ),

  /**
   * Omit `sections` for everything; pass the layout's sections to compute only those.
   * `legalEntityId` narrows every figure to one company the caller can already see.
   */
  hr: (sections?: string, legalEntityId?: string) => {
    const params = new URLSearchParams();
    if (sections !== undefined) params.set("sections", sections);
    if (legalEntityId) params.set("legal_entity_id", legalEntityId);
    const qs = params.toString();
    return api.get<Record<string, unknown>>(`/v1/dashboard/hr${qs ? `?${qs}` : ""}`);
  },

  superAdmin: () => api.get<Record<string, unknown>>("/v1/dashboard/super-admin"),

  /** `dashboard`: "hr" is the widget grid, "overview" the HRMS overview's cards. */
  layout: (dashboard: LayoutDashboard = "hr") => api.get<DashboardLayout>(`/v1/dashboard/layout?dashboard=${dashboard}`),
  saveLayout: (widgets: LayoutItem[], dashboard: LayoutDashboard = "hr") =>
    api.put<DashboardLayout>(`/v1/dashboard/layout?dashboard=${dashboard}`, { widgets }),
  resetLayout: (dashboard: LayoutDashboard = "hr") => api.delete<DashboardLayout>(`/v1/dashboard/layout?dashboard=${dashboard}`),
};

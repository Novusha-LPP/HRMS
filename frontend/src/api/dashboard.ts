import { api } from "./client";

export interface CelebrationPerson {
  id: string;
  name: string;
  company: string;
  is_self: boolean;
}

export interface LoginCelebrations {
  date: string;
  timezone: string;
  personal: { birthday: boolean; anniversary_years: number | null };
  birthdays: CelebrationPerson[];
  anniversaries: (CelebrationPerson & { years: number })[];
}

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

/** A holiday on the employee's own calendar; optional ones can be taken but aren't a day off. */
export interface UpcomingHoliday {
  date: string;
  name: string;
  is_optional: boolean;
  days_away: number;
}

export interface EmployeeDashboard {
  today: {
    date: string;
    is_punched_in: boolean;
    punch_in_time: string | null;
    effective_minutes: number;
    status: string;
  };
  month_summary: {
    month: string;
    present: number;
    absent: number;
    late: number;
    working_days: number;
    worked_minutes?: number;
  };
  onboarding: { case_id: string; total: number; completed: number; pct: number } | null;
  upcoming_holidays?: UpcomingHoliday[];
}

/** One direct report's day, as the attendance register would show it. */
export interface TeamMemberToday {
  status: string;
  is_off_day: boolean;
  holiday_name: string | null;
  leave_type: string | null;
  first_punch_in: string | null;
  last_punch_out: string | null;
  effective_minutes: number;
  late_by_minutes: number;
  is_checked_in: boolean;
  shift_start: string;
  shift_end: string;
  timezone: string;
}

export interface TeamMember {
  employment_id: string;
  name: string;
  employee_number: string;
  designation: string | null;
  department: string | null;
  hire_date: string;
  /** Null until their joining date. */
  today: TeamMemberToday | null;
  month: { present: number; late: number; absent: number; worked_minutes: number };
}

export interface TeamLeave {
  id: string;
  employment_id: string;
  name: string;
  leave_type: string;
  color: string;
  from_date: string;
  to_date: string;
  days: number;
  status: string;
}

export interface TeamOverview {
  date: string;
  month: string;
  members: TeamMember[];
  upcoming_leave: TeamLeave[];
}

export const dashboardApi = {
  celebrations: () => api.get<LoginCelebrations>("/v1/dashboard/celebrations"),

  employee: (employmentId: string) =>
    api.get<EmployeeDashboard>(`/v1/dashboard/employee?employment_id=${employmentId}`),

  /** The caller's own direct reports. */
  team: () => api.get<TeamOverview>("/v1/dashboard/team"),

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

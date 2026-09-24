import { api } from "./client";

export const dashboardApi = {
  employee: (employmentId: string) =>
    api.get<Record<string, unknown>>(`/v1/dashboard/employee?employment_id=${employmentId}`),

  manager: (managerEmpId: string) =>
    api.get<Record<string, unknown>>(
      `/v1/dashboard/manager?manager_employment_id=${managerEmpId}`,
    ),

  hr: () => api.get<Record<string, unknown>>("/v1/dashboard/hr"),

  superAdmin: () => api.get<Record<string, unknown>>("/v1/dashboard/super-admin"),
};

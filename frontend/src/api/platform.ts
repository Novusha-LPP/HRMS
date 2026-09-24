import { platformApi } from "./platformClient";

export type PlatformRole = "ADMIN" | "VIEWER";

export interface PlatformLoginResponse {
  access_token: string;
  expires_in: number;
  name: string;
  email: string;
  role: PlatformRole;
}

export interface TenantSummary {
  id: string;
  slug: string;
  display_name: string;
  status: string;
  plan: string;
  legal_entity_count: number;
  created_at: string;
  archived_at: string | null;
}

export interface TenantListResponse {
  items: TenantSummary[];
  total: number;
}

export interface TenantLegalEntity {
  id: string;
  name: string;
  short_name: string | null;
  status: string;
}

export interface TenantDetail extends TenantSummary {
  country_code: string;
  employee_count: number;
  legal_entities: TenantLegalEntity[];
}

export type CompanyMode = "NEW_TENANT" | "SUBSIDIARY";

export interface PlatformCompanyResponse {
  mode: CompanyMode;
  tenant_id: string;
  tenant_name: string;
  legal_entity_id: string;
  legal_entity_name: string;
  admin_email: string | null;
}

export interface PlatformAdminSummary {
  id: string;
  name: string;
  email: string;
  role: PlatformRole;
  status: string;
  created_at: string;
  last_login_at: string | null;
  is_you: boolean;
}

export interface AuditLogEntry {
  id: string;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: string | null;
  target_label: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogResponse {
  items: AuditLogEntry[];
  total: number;
}

export interface PlatformMe {
  name: string;
  email: string;
  role: PlatformRole;
}

export const platformTenantsApi = {
  login: (email: string, password: string) =>
    platformApi.post<PlatformLoginResponse>("/v1/platform/login", { email, password }),
  me: () => platformApi.get<PlatformMe>("/v1/platform/me"),
  forgotPassword: (email: string) =>
    platformApi.post<{ message: string; dev_reset_url: string | null }>("/v1/platform/forgot-password", { email }),
  resetPassword: (token: string, new_password: string) =>
    platformApi.post<{ message: string }>("/v1/platform/reset-password", { token, new_password }),

  listTenants: (params: { q?: string; include_archived?: boolean; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.include_archived) qs.set("include_archived", "true");
    qs.set("limit", String(params.limit ?? 25));
    qs.set("offset", String(params.offset ?? 0));
    return platformApi.get<TenantListResponse>(`/v1/platform/tenants?${qs.toString()}`);
  },
  getTenant: (id: string) => platformApi.get<TenantDetail>(`/v1/platform/tenants/${id}`),
  updateTenant: (id: string, body: { status?: string; plan?: string }) =>
    platformApi.patch<TenantDetail>(`/v1/platform/tenants/${id}`, body),
  archiveTenant: (id: string) => platformApi.post<TenantDetail>(`/v1/platform/tenants/${id}/archive`, {}),
  restoreTenant: (id: string) => platformApi.post<TenantDetail>(`/v1/platform/tenants/${id}/restore`, {}),

  createCompany: (body: {
    company_name: string;
    country_code?: string;
    mode: CompanyMode;
    parent_tenant_id?: string;
    admin_email?: string;
    admin_password?: string;
  }) => platformApi.post<PlatformCompanyResponse>("/v1/platform/companies", body),

  listAdmins: () => platformApi.get<PlatformAdminSummary[]>("/v1/platform/admins"),
  createAdmin: (body: { name: string; email: string; password: string; role: PlatformRole }) =>
    platformApi.post<PlatformAdminSummary>("/v1/platform/admins", body),
  updateAdmin: (id: string, body: { status?: string; role?: PlatformRole }) =>
    platformApi.patch<PlatformAdminSummary>(`/v1/platform/admins/${id}`, body),

  getAuditLog: (params: { limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    qs.set("limit", String(params.limit ?? 50));
    qs.set("offset", String(params.offset ?? 0));
    return platformApi.get<AuditLogResponse>(`/v1/platform/audit-log?${qs.toString()}`);
  },
};

import { api } from "./client";

export type ScopeType = "ALL" | "LEGAL_ENTITY" | "SELF" | "DIRECT_REPORTS" | "ALL_REPORTS";

export interface Role {
  name: string;
  description: string | null;
  permissions: string[];
}

export interface UserAccount {
  id: string;
  email: string | null;
  status: string;
  role: string;
  scope_type: ScopeType;
  legal_entity_ids: string[];
  employment_id: string | null;
  employee_name: string | null;
  created_at: string;
  last_login_at: string | null;
}

export const usersApi = {
  listRoles: () => api.get<Role[]>("/v1/roles"),
  listUsers: () => api.get<UserAccount[]>("/v1/users"),
  createUser: (body: {
    email: string;
    password: string;
    role: string;
    scope_type: ScopeType;
    legal_entity_ids?: string[];
    employment_id?: string;
  }) => api.post<UserAccount>("/v1/users", body),
};

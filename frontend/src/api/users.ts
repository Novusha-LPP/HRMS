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
  /** The linked employee's state. A SEPARATED employee's login is ACTIVE but cannot sign in. */
  employment_state: string | null;
  can_sign_in: boolean;
  must_change_password: boolean;
}

export const usersApi = {
  listRoles: () => api.get<Role[]>("/v1/roles"),
  listUsersPage: (offset = 0, limit = 200) => api.get<UserAccount[]>(`/v1/users?limit=${limit}&offset=${offset}`),
  listUsers: async () => {
    const users: UserAccount[] = [];
    for (let offset = 0; ; offset += 200) {
      const page = await api.get<UserAccount[]>(`/v1/users?limit=200&offset=${offset}`);
      users.push(...page);
      if (page.length < 200) return users;
    }
  },
  createUser: (body: {
    email: string;
    password: string;
    role: string;
    scope_type: ScopeType;
    legal_entity_ids?: string[];
    employment_id?: string;
    must_change_password?: boolean;
  }) => api.post<UserAccount>("/v1/users", body),
  /** INACTIVE locks the person out at once, existing sessions included. */
  setStatus: (id: string, status: "ACTIVE" | "INACTIVE") =>
    api.patch<UserAccount>(`/v1/users/${id}`, { status }),
  /** Sets a temporary password; the person must replace it at their next sign-in. */
  resetPassword: (id: string, password: string) =>
    api.post<UserAccount>(`/v1/users/${id}/reset-password`, { password }),
};

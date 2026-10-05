import { resetSessionCache } from "../lib/session";
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, useCallback } from "react";
import type { ReactNode } from "react";
import { api, ApiError, getAuthToken, setAuthToken, setUnauthorizedHandler } from "../api/client";
import { SignInError } from "../lib/signInError";
import { setErrorTrackingUser } from "../lib/errorTracking";

// The backend can grant several fine-grained roles per user (see
// backend/src/hrms/core/authz.py — SUPER_ADMIN, HR_MANAGER, MANAGER,
// EMPLOYEE, ACCOUNTANT, ...). The UI only branches on this coarse bucket for
// layout/dashboard selection; every actual access decision is re-checked by
// the API against the full role/permission set, not this client-side value.
export type UserRole = "EMPLOYEE" | "MANAGER" | "HR" | "SUPER_ADMIN";

interface LegalEntitySummary {
  id: string;
  name: string;
}

export interface AuthUser {
  id: string;
  tenantId: string;
  tenantName: string;
  employmentId: string | null;
  name: string;
  email: string | null;
  role: UserRole;
  roles: string[];
  permissions: string[];
  isAllScope: boolean;
  legalEntities: LegalEntitySummary[];
  /** True until the person has replaced an imported / admin-issued password. */
  mustChangePassword: boolean;
  mfaRequired: boolean;
}

interface MeResponse {
  id: string;
  email: string | null;
  name: string;
  employment_id: string | null;
  tenant_id: string;
  tenant_name: string;
  roles: string[];
  permissions: string[];
  is_all_scope: boolean;
  legal_entities: LegalEntitySummary[];
  must_change_password?: boolean;
  mfa_required?: boolean;
}

interface LoginResponse {
  access_token: string;
  expires_in: number;
  user: MeResponse;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  /** `company` (the company code) is only needed when the API answers COMPANY_REQUIRED. */
  login: (identifier: string, password: string, company?: string, otp?: string) => Promise<void>;
  /** Replaces the password and swaps in the fresh session the server returns. */
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  registerCompany: (body: { company_name: string; country_code?: string; admin_email: string; admin_password: string }) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const TOKEN_KEY = "hrms_token";

function primaryRole(roles: string[]): UserRole {
  if (roles.includes("SUPER_ADMIN")) return "SUPER_ADMIN";
  if (roles.includes("HR_MANAGER") || roles.includes("ACCOUNTANT")) return "HR";
  if (roles.includes("MANAGER")) return "MANAGER";
  return "EMPLOYEE";
}

function toAuthUser(m: MeResponse): AuthUser {
  return {
    id: m.id,
    tenantId: m.tenant_id,
    tenantName: m.tenant_name,
    employmentId: m.employment_id,
    name: m.name,
    email: m.email,
    role: primaryRole(m.roles),
    roles: m.roles,
    permissions: m.permissions,
    isAllScope: m.is_all_scope,
    legalEntities: m.legal_entities,
    mustChangePassword: m.must_change_password ?? false,
    mfaRequired: m.mfa_required ?? false,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const resetCache = () => resetSessionCache(queryClient);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    localStorage.removeItem(TOKEN_KEY); // Remove legacy persisted bearer credentials.
    const token = getAuthToken();
    api.get<MeResponse>("/v1/auth/me")
      .then((me) => { if (getAuthToken() === token) setUser(toAuthUser(me)); })
      .catch((error: unknown) => {
        if (getAuthToken() !== token) return;
        if (!(error instanceof ApiError) || error.status !== 401) return;
        // Expired/invalid token — drop it silently and fall back to the login page.
        localStorage.removeItem(TOKEN_KEY);
        setAuthToken();
      })
      .finally(() => setLoading(false));
  }, []);

  const startSession = (res: LoginResponse) => {
    resetCache();
    setAuthToken();
    setUser(toAuthUser(res.user));
  };

  const login = async (identifier: string, password: string, company?: string, otp?: string) => {
    try {
      const body: Record<string, string> = { identifier, password };
      if (otp?.trim()) body.otp = otp.trim();
      if (company?.trim()) body.tenant = company.trim();
      startSession(await api.post<LoginResponse>("/v1/auth/login", body));
    } catch (e) {
      throw e instanceof ApiError ? new SignInError(e.message || "Invalid credentials", e.code, e.status) : e;
    }
  };

  const changePassword = async (currentPassword: string, newPassword: string) => {
    try {
      // The old token stops working the moment the password changes, so the response carries a new one.
      startSession(await api.post<LoginResponse>("/v1/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      }));
    } catch (e) {
      throw e instanceof ApiError ? new SignInError(e.message || "Couldn't change your password", e.code, e.status) : e;
    }
  };

  const registerCompany = async (body: { company_name: string; country_code?: string; admin_email: string; admin_password: string }) => {
    try {
      const res = await api.post<LoginResponse>("/v1/auth/register-company", body);
      resetCache();
      setAuthToken();
      setUser(toAuthUser(res.user));
    } catch (e) {
      throw e instanceof ApiError ? new Error(e.message || "Couldn't register company") : e;
    }
  };

  const logout = useCallback(() => {
    void api.post("/v1/auth/logout", {}).catch(() => undefined);
    resetSessionCache(queryClient);
    localStorage.removeItem(TOKEN_KEY);
    setAuthToken();
    setUser(null);
  }, [queryClient]);

  useEffect(() => {
    setErrorTrackingUser(user ? { id: user.id, tenantId: user.tenantId } : null);
  }, [user]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      resetSessionCache(queryClient);
      setAuthToken();
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, [queryClient]);

  return (
    <AuthContext.Provider value={{ user, loading, login, changePassword, registerCompany, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

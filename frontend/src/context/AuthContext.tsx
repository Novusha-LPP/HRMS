import { resetSessionCache } from "../lib/session";
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, useCallback } from "react";
import type { ReactNode } from "react";
import { api, ApiError, getAuthToken, setAuthToken, setUnauthorizedHandler } from "../api/client";

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
}

interface LoginResponse {
  access_token: string;
  expires_in: number;
  user: MeResponse;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
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
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const resetCache = () => resetSessionCache(queryClient);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(() => !!localStorage.getItem(TOKEN_KEY));

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return;
    setAuthToken(token);
    api.get<MeResponse>("/v1/auth/me")
      .then((me) => { if (getAuthToken() === token) setUser(toAuthUser(me)); })
      .catch(() => {
        if (getAuthToken() !== token) return;
        // Expired/invalid token — drop it silently and fall back to the login page.
        localStorage.removeItem(TOKEN_KEY);
        setAuthToken(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    try {
      const res = await api.post<LoginResponse>("/v1/auth/login", { email, password });
      resetCache();
      localStorage.setItem(TOKEN_KEY, res.access_token);
      setAuthToken(res.access_token);
      setUser(toAuthUser(res.user));
    } catch (e) {
      throw e instanceof ApiError ? new Error(e.message || "Invalid email or password") : e;
    }
  };

  const registerCompany = async (body: { company_name: string; country_code?: string; admin_email: string; admin_password: string }) => {
    try {
      const res = await api.post<LoginResponse>("/v1/auth/register-company", body);
      resetCache();
      localStorage.setItem(TOKEN_KEY, res.access_token);
      setAuthToken(res.access_token);
      setUser(toAuthUser(res.user));
    } catch (e) {
      throw e instanceof ApiError ? new Error(e.message || "Couldn't register company") : e;
    }
  };

  const logout = useCallback(() => {
    resetSessionCache(queryClient);
    localStorage.removeItem(TOKEN_KEY);
    setAuthToken(null);
    setUser(null);
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  return (
    <AuthContext.Provider value={{ user, loading, login, registerCompany, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

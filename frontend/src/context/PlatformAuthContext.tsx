import { resetSessionCache } from "../lib/session";
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { PlatformApiError, getPlatformSession, platformApi, setPlatformToken } from "../api/platformClient";
import { platformTenantsApi } from "../api/platform";
import type { PlatformRole } from "../api/platform";

interface PlatformAdmin {
  name: string;
  email: string;
  role: PlatformRole;
  mfa_required?: boolean;
}

interface PlatformAuthContextValue {
  admin: PlatformAdmin | null;
  loading: boolean;
  login: (email: string, password: string, otp?: string) => Promise<void>;
  logout: () => void;
}

const PlatformAuthContext = createContext<PlatformAuthContextValue | null>(null);
const TOKEN_KEY = "hrms_platform_token";
const ADMIN_KEY = "hrms_platform_admin";

export function PlatformAuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const resetCache = () => resetSessionCache(queryClient);
  const [admin, setAdmin] = useState<PlatformAdmin | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ADMIN_KEY);
    const token = getPlatformSession();

    // Role/status are resolved fresh from the DB on every /v1/platform/*
    // request — the UI should match rather than trust a cached login
    // response indefinitely. This also fixes a role/name change made by
    // another admin, or a cached login from before a field existed here.
    platformTenantsApi.me()
      .then((me) => {
        if (getPlatformSession() !== token) return;
        setAdmin(me);

      })
      .catch((error: unknown) => {
        if (getPlatformSession() !== token) return;
        // Keep the session during an outage; only explicit rejection invalidates it.
        if (!(error instanceof PlatformApiError) || error.status !== 401) return;
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(ADMIN_KEY);
        setPlatformToken();
        setAdmin(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string, otp?: string) => {
    await platformTenantsApi.login(email, password, otp);
    const nextAdmin = await platformTenantsApi.me();
    resetCache();
    setPlatformToken();
    setAdmin(nextAdmin);
  };

  const logout = () => {
    void platformApi.post("/v1/platform/logout", {}).catch(() => undefined);
    resetCache();
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ADMIN_KEY);
    setPlatformToken();
    setAdmin(null);
  };

  return (
    <PlatformAuthContext.Provider value={{ admin, loading, login, logout }}>
      {children}
    </PlatformAuthContext.Provider>
  );
}

export function usePlatformAuth() {
  const ctx = useContext(PlatformAuthContext);
  if (!ctx) throw new Error("usePlatformAuth must be used inside PlatformAuthProvider");
  return ctx;
}

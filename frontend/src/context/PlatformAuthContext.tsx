import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { setPlatformToken } from "../api/platformClient";
import { platformTenantsApi } from "../api/platform";
import type { PlatformRole } from "../api/platform";

interface PlatformAdmin {
  name: string;
  email: string;
  role: PlatformRole;
}

interface PlatformAuthContextValue {
  admin: PlatformAdmin | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const PlatformAuthContext = createContext<PlatformAuthContextValue | null>(null);
const TOKEN_KEY = "hrms_platform_token";
const ADMIN_KEY = "hrms_platform_admin";

export function PlatformAuthProvider({ children }: { children: ReactNode }) {
  const [admin, setAdmin] = useState<PlatformAdmin | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    const savedAdmin = localStorage.getItem(ADMIN_KEY);
    if (!token) {
      setLoading(false);
      return;
    }
    setPlatformToken(token);
    if (savedAdmin) setAdmin(JSON.parse(savedAdmin)); // paint immediately, may be stale

    // Role/status are resolved fresh from the DB on every /v1/platform/*
    // request — the UI should match rather than trust a cached login
    // response indefinitely. This also fixes a role/name change made by
    // another admin, or a cached login from before a field existed here.
    platformTenantsApi.me()
      .then((me) => {
        setAdmin(me);
        localStorage.setItem(ADMIN_KEY, JSON.stringify(me));
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(ADMIN_KEY);
        setPlatformToken(null);
        setAdmin(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const res = await platformTenantsApi.login(email, password);
    const nextAdmin = { name: res.name, email: res.email, role: res.role };
    localStorage.setItem(TOKEN_KEY, res.access_token);
    localStorage.setItem(ADMIN_KEY, JSON.stringify(nextAdmin));
    setPlatformToken(res.access_token);
    setAdmin(nextAdmin);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ADMIN_KEY);
    setPlatformToken(null);
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

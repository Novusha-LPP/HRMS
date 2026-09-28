const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8015";

export class PlatformApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Separate from api/client.ts's authToken on purpose — a platform admin is
// not a tenant user, and the two token types are rejected by each other's
// endpoints server-side (see core/authn.py), so keeping them in entirely
// separate variables/storage keys avoids ever mixing them up client-side too.
let platformToken: string | null = null;

export function setPlatformToken(token: string | null) {
  platformToken = token;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (platformToken) headers["Authorization"] = `Bearer ${platformToken}`;

  const requestToken = platformToken;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (requestToken !== platformToken) throw new Error("Session changed");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new PlatformApiError(res.status, body.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json();
  if (requestToken !== platformToken) throw new Error("Session changed");
  return data;
}

export const platformApi = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
};

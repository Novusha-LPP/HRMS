const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8015";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// Held in memory so every request picks it up immediately after login/logout,
// without re-reading localStorage on the hot path. AuthContext is the only
// thing that calls this. The backend derives tenant + identity entirely from
// this token now — there is no client-supplied tenant header anymore.
let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

export function getAuthToken(): string | null {
  return authToken;
}

export const API_BASE_URL = BASE;

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const requestToken = authToken;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (requestToken !== authToken) throw new Error("Session changed");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== "/v1/auth/login") onUnauthorized?.();
    throw new ApiError(res.status, body.code ?? "UNKNOWN", body.detail ?? res.statusText);
  }

  if (res.status === 204) return undefined as T;
  const data = await res.json();
  if (requestToken !== authToken) throw new Error("Session changed");
  return data;
}

export const api = {
  get:      <T>(path: string) => request<T>(path),
  post:     <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  postForm: <T>(path: string, formData: FormData) =>
    request<T>(path, { method: "POST", body: formData }),
  patch:    <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete:   (path: string) => request<void>(path, { method: "DELETE" }),
};

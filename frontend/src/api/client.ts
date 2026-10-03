import { withRequestDeadline } from "../lib/requestDeadline";
import { runtimeConfig } from "../lib/runtimeConfig";
import { logger } from "../lib/logger";
import { generateRequestId } from "../lib/uuid";

const BASE = runtimeConfig.apiUrl;

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  details?: unknown;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId?: string,
    details?: unknown
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
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
export const API_DOCS_URL = `${BASE.replace(/\/+$/, "")}/docs`;

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  // Attach or generate client request correlation ID
  const clientRequestId = headers["X-Request-ID"] || generateRequestId();
  headers["X-Request-ID"] = clientRequestId;

  const requestToken = authToken;
  return withRequestDeadline(async (signal) => {
  const res = await fetch(`${BASE}${path}`, { ...options, headers, signal });

  if (requestToken !== authToken) throw new Error("Session changed");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== "/v1/auth/login") onUnauthorized?.();

    const requestId =
      body.request_id ||
      body.error?.request_id ||
      res.headers.get("x-request-id") ||
      clientRequestId;
    const code = body.code || body.error?.code || "UNKNOWN";
    const detail = body.detail || body.error?.message || res.statusText;
    const details = body.error?.details;

    logger.error(`API ${options.method ?? "GET"} ${path} failed with ${res.status}`, {
      code,
      requestId,
      detail,
    });

    throw new ApiError(res.status, code, detail, requestId, details);
  }

  if (res.status === 204) return undefined as T;
  const data = await res.json();
  if (requestToken !== authToken) throw new Error("Session changed");
  return data;
  }, options.signal);
}

export const api = {
  get:      <T>(path: string) => request<T>(path),
  post:     <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  postForm: <T>(path: string, formData: FormData) =>
    request<T>(path, { method: "POST", body: formData }),
  patch:    <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put:      <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  delete:   <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
};

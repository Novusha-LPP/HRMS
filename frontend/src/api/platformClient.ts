import { withRequestDeadline } from "../lib/requestDeadline";
import { runtimeConfig } from "../lib/runtimeConfig";
import { logger } from "../lib/logger";
import { generateRequestId } from "../lib/uuid";

const BASE = runtimeConfig.apiUrl;

export class PlatformApiError extends Error {
  status: number;
  requestId?: string;

  constructor(status: number, message: string, requestId?: string) {
    super(message);
    this.status = status;
    this.requestId = requestId;
  }
}

// A separate identity generation counter for the platform cookie realm.
let platformToken = 0;

export function setPlatformToken() {
  platformToken += 1;
}

export function getPlatformSession(): number { return platformToken; }

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  headers["X-HRMS-Session"] = "cookie";

  const clientRequestId = headers["X-Request-ID"] || generateRequestId();
  headers["X-Request-ID"] = clientRequestId;

  const requestToken = platformToken;
  return withRequestDeadline(async (signal) => {
  const res = await fetch(`${BASE}${path}`, { ...options, headers, signal, credentials: "include" });
  if (requestToken !== platformToken) throw new Error("Session changed");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const requestId =
      body.request_id ||
      body.error?.request_id ||
      res.headers.get("x-request-id") ||
      clientRequestId;
    const detail = body.detail ?? body.error?.message ?? res.statusText;

    logger.error(`Platform API ${options.method ?? "GET"} ${path} failed with ${res.status}`, {
      requestId,
      detail,
    });

    throw new PlatformApiError(res.status, detail, requestId);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json();
  if (requestToken !== platformToken) throw new Error("Session changed");
  return data;
  }, options.signal);
}

export const platformApi = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
};

/**
 * Error tracking (Sentry) for the web app. Off unless VITE_SENTRY_DSN is set at build time;
 * the SDK is only downloaded when it is, so builds without it carry none of its weight.
 *
 * What is reported: uncaught errors, unhandled promise rejections and React render crashes
 * (ErrorBoundary → logger.error). What is not: failed API calls. The API reports its own
 * 5xx errors with the same request id, and a 4xx is an outcome, not a bug.
 *
 * Privacy: no default PII, the user is identified by account and tenant id only, and
 * query strings are dropped from URLs in events and breadcrumbs.
 */
import { ApiError } from "../api/client";

type Sentry = typeof import("@sentry/react");

let sentry: Sentry | null = null;
let pendingUser: { id: string; tenantId: string } | null = null;

const stripQuery = (url: string) => url.split("?")[0];

export async function initErrorTracking(): Promise<void> {
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
  if (!dsn) return;
  const lib = await import("@sentry/react");
  lib.init({
    dsn,
    release: `hrms@${__APP_VERSION__}`,
    environment: (import.meta.env.VITE_SENTRY_ENVIRONMENT as string | undefined) ?? import.meta.env.MODE,
    sendDefaultPii: false,
    beforeSend(event, hint) {
      if (hint.originalException instanceof ApiError) return null;
      if (event.request?.url) event.request.url = stripQuery(event.request.url);
      delete event.request?.cookies;
      delete event.request?.query_string;
      return event;
    },
    beforeBreadcrumb(crumb) {
      if (crumb.category === "ui.input") return null;
      if (typeof crumb.data?.url === "string") crumb.data.url = stripQuery(crumb.data.url);
      return crumb;
    },
  });
  lib.setTag("commit", __GIT_SHA__);
  sentry = lib;
  setErrorTrackingUser(pendingUser);
}

/** Called on sign-in and sign-out. Ids only — never a name or an email. */
export function setErrorTrackingUser(user: { id: string; tenantId: string } | null): void {
  pendingUser = user;
  if (!sentry) return;
  sentry.setUser(user ? { id: user.id } : null);
  sentry.setTag("tenant_id", user?.tenantId ?? null);
}

export function reportError(error: unknown, context?: unknown): void {
  if (!sentry || !(error instanceof Error) || error instanceof ApiError) return;
  sentry.captureException(error, context && typeof context === "object" ? { extra: { ...context } } : undefined);
}

/**
 * Settings that differ per environment (local / testing / production), read at runtime from
 * /config.js so one build can be promoted from testing to production unchanged. The web
 * container writes config.js from its environment at start-up (deploy/web/entrypoint.sh);
 * locally public/config.js is empty and the Vite variables in .env apply.
 */
interface InjectedConfig {
  apiUrl?: string;
  environment?: string;
  sentryDsn?: string;
  sentryEnvironment?: string;
}

const injected: InjectedConfig =
  (globalThis as { __HRMS_CONFIG__?: InjectedConfig }).__HRMS_CONFIG__ ?? {};
const value = (v: string | undefined) => (v && v.trim() ? v.trim() : undefined);

export type AppEnvironment = "local" | "testing" | "production";

export const runtimeConfig = {
  apiUrl: value(injected.apiUrl) ?? value(import.meta.env.VITE_API_URL) ?? "http://localhost:8015",
  environment: (value(injected.environment) ?? "local") as AppEnvironment,
  sentryDsn: value(injected.sentryDsn) ?? value(import.meta.env.VITE_SENTRY_DSN),
  sentryEnvironment:
    value(injected.sentryEnvironment) ??
    value(injected.environment) ??
    value(import.meta.env.VITE_SENTRY_ENVIRONMENT) ??
    import.meta.env.MODE,
};

/** The API's interactive docs. Deployed APIs serve them only when HRMS_API_DOCS_ENABLED is on. */
export const API_DOCS_URL = `${runtimeConfig.apiUrl.replace(/\/$/, "")}/docs`;

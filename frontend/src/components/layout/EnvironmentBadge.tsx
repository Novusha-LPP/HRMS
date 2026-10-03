import { runtimeConfig } from "../../lib/runtimeConfig";

/**
 * Says which environment this is, on every page including sign-in, so nobody mistakes the
 * testing site for production. Production and local show nothing.
 */
export function EnvironmentBadge() {
  if (runtimeConfig.environment !== "testing") return null;
  return (
    <div
      role="status"
      className="pointer-events-none fixed bottom-3 right-3 z-[60] rounded-full border border-amber-300 bg-amber-100 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-amber-900 shadow-sm dark:border-amber-700 dark:bg-amber-900/80 dark:text-amber-100"
    >
      Testing environment
    </div>
  );
}

/**
 * Enterprise frontend structured logging utility.
 *
 * Provides:
 * - Level-gated console output (suppressing verbose debug logs in production builds).
 * - Standardized log prefixes with ISO timestamp and origin.
 * - Structured context and error capture.
 * - Extensible hook for remote error reporting / APM tools (e.g. Sentry, Datadog).
 */

export type LogLevel = "debug" | "info" | "warn" | "error";

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

// Default: DEBUG in development, INFO in production
const currentLevel: LogLevel = import.meta.env.DEV ? "debug" : "info";

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVELS[level] >= LOG_LEVELS[currentLevel];
}

function formatPrefix(level: LogLevel): string {
  const timestamp = new Date().toISOString().slice(11, 23);
  return `[HRMS ${timestamp}] [${level.toUpperCase()}]`;
}

export const logger = {
  debug(message: string, context?: unknown): void {
    if (!shouldLog("debug")) return;
    const prefix = formatPrefix("debug");
    if (context !== undefined) {
      console.debug(prefix, message, context);
    } else {
      console.debug(prefix, message);
    }
  },

  info(message: string, context?: unknown): void {
    if (!shouldLog("info")) return;
    const prefix = formatPrefix("info");
    if (context !== undefined) {
      console.info(prefix, message, context);
    } else {
      console.info(prefix, message);
    }
  },

  warn(message: string, context?: unknown): void {
    if (!shouldLog("warn")) return;
    const prefix = formatPrefix("warn");
    if (context !== undefined) {
      console.warn(prefix, message, context);
    } else {
      console.warn(prefix, message);
    }
  },

  error(message: string, error?: unknown, context?: unknown): void {
    if (!shouldLog("error")) return;
    const prefix = formatPrefix("error");
    if (error !== undefined && context !== undefined) {
      console.error(prefix, message, error, context);
    } else if (error !== undefined) {
      console.error(prefix, message, error);
    } else {
      console.error(prefix, message);
    }
  },
};

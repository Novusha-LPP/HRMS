import { format, parseISO } from "date-fns";

/**
 * Format a date-only string ("1990-03-04") without shifting it by the viewer's timezone.
 * `new Date("1990-03-04")` is midnight UTC, so anywhere west of UTC it renders as the 3rd.
 * parseISO reads a date-only string as local midnight, which is what a birthday means.
 */
export function formatDateOnly(value: string, pattern = "d MMM yyyy"): string {
  return format(parseISO(value), pattern);
}

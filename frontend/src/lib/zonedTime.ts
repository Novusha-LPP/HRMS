/**
 * Wall-clock dates and times in a named timezone (the attendance policy's), converted to and from
 * instants without a library. Attendance is shown and edited on the policy's clock, whatever the
 * browser's own timezone is.
 */

function parts(instant: Date, tz: string) {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const p = Object.fromEntries(fmt.formatToParts(instant).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
}

/** The local date (YYYY-MM-DD) and time (HH:mm) of an instant in `tz`. */
export function zonedParts(iso: string, tz: string) {
  return parts(new Date(iso), tz);
}

function offsetMinutes(instant: number, tz: string) {
  const { date, time } = parts(new Date(instant), tz);
  const wall = Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10), +time.slice(0, 2), +time.slice(3, 5));
  return Math.round((wall - Math.floor(instant / 60_000) * 60_000) / 60_000);
}

/** The instant (ISO, UTC) of a local date and time in `tz`. */
export function zonedToIso(date: string, time: string, tz: string) {
  const wall = Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10), +time.slice(0, 2), +time.slice(3, 5));
  let instant = wall - offsetMinutes(wall, tz) * 60_000;
  instant = wall - offsetMinutes(instant, tz) * 60_000; // settles across a DST change
  return new Date(instant).toISOString();
}

/** "09:30 AM" on the `tz` clock. */
export function clock12(iso: string, tz: string) {
  const [h, m] = zonedParts(iso, tz).time.split(":").map(Number);
  return `${String(h % 12 || 12).padStart(2, "0")}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

/** YYYY-MM-DD of the day after `date`. */
export function nextDate(date: string) {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

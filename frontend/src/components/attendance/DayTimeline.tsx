import type { RegisterDay } from "../../api/time";
import { daySegments, shiftWindow } from "./registerModel";

const SEGMENT_CLASS = {
  work: "bg-success",
  break: "bg-warning",
  out: "bg-transparent",
  open: "bg-success/45 bg-[length:8px_8px] bg-[linear-gradient(45deg,rgb(255_255_255/0.35)_25%,transparent_25%,transparent_50%,rgb(255_255_255/0.35)_50%,rgb(255_255_255/0.35)_75%,transparent_75%)]",
} as const;

const hourLabel = (m: number) => {
  const h = Math.floor(((m / 60) % 24 + 24) % 24);
  return `${h % 12 || 12}${h < 12 ? "a" : "p"}`;
};

/**
 * A day drawn on a time axis: the shift as a light band, worked time in green, breaks in amber,
 * time checked out in between as a gap, and an open session striped up to now.
 * `range` is in minutes from the work date's midnight, shared across rows so they line up.
 */
export function DayTimeline({ day, range, size = "sm" }: {
  day: RegisterDay;
  range: { from: number; to: number };
  size?: "sm" | "lg";
}) {
  const span = range.to - range.from;
  const pct = (m: number) => `${Math.min(100, Math.max(0, ((m - range.from) / span) * 100))}%`;
  const width = (a: number, b: number) => `${Math.max(0, Math.min(100, ((Math.min(b, range.to) - Math.max(a, range.from)) / span) * 100))}%`;
  const shift = shiftWindow(day);
  const segments = daySegments(day);
  const ticks = [];
  for (let m = Math.ceil(range.from / 180) * 180; m <= range.to; m += 180) ticks.push(m);

  return (
    <div className={size === "lg" ? "pb-5" : ""}>
      <div className={`relative w-full overflow-hidden rounded-full bg-muted ${size === "lg" ? "h-3" : "h-1.5"}`}>
        <div className="absolute inset-y-0 bg-brand-500/15" style={{ left: pct(shift.from), width: width(shift.from, shift.to) }} />
        {segments.map((s, i) => (
          <div
            key={i}
            className={`absolute inset-y-0 ${SEGMENT_CLASS[s.kind]} ${s.kind === "open" ? "animate-pulse" : ""}`}
            style={{ left: pct(s.from), width: width(s.from, s.to) }}
          />
        ))}
      </div>
      {size === "lg" && (
        <div className="relative mt-1 h-3 text-[10px] tabular-nums text-fg-subtle">
          {ticks.map((m) => (
            <span key={m} className="absolute -translate-x-1/2" style={{ left: pct(m) }}>{hourLabel(m)}</span>
          ))}
        </div>
      )}
    </div>
  );
}

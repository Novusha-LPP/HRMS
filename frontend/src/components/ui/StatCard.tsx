import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { ArrowDownRight, ArrowUpRight } from "../icons/ThemeIcons";
import { Sparkline } from "./Charts";
import { Skeleton } from "./Feedback";

export function StatCard({ label, value, icon: Icon, iconTone = "blue", delta, deltaSuffix = "", hint, spark, invertDelta, loading }: {
  label: string;
  value: ReactNode;
  icon: LucideIcon;
  iconTone?: "blue" | "green" | "red" | "purple" | "orange" | "teal";
  delta?: number;
  deltaSuffix?: string;
  hint?: ReactNode;
  spark?: number[];
  invertDelta?: boolean;
  loading?: boolean;
}) {
  const good = delta !== undefined && (invertDelta ? delta <= 0 : delta >= 0);
  return (
    <div className="stat-card card flex flex-col p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="stat-label text-[13px] font-medium text-fg-muted">{label}</span>
        <span data-icon-tone={iconTone} className="stat-icon grid h-8 w-8 place-items-center rounded-lg border border-line bg-panel text-fg-subtle">
          <Icon size={15} />
        </span>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className="min-w-0">
          {loading ? (
            <Skeleton className="h-8 w-20" />
          ) : (
            <div className="stat-value text-[28px] font-semibold leading-none tracking-tight tabular-nums text-fg">{value}</div>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-fg-subtle">
            {delta !== undefined && (
              <span
                className={`inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium tabular-nums ${
                  good ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
                }`}
              >
                {delta >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                {Math.abs(delta)}{deltaSuffix}
              </span>
            )}
            {hint && <span className="truncate">{hint}</span>}
          </div>
        </div>
        {spark && <Sparkline data={spark} className={good || delta === undefined ? "text-brand-500" : "text-danger"} />}
      </div>
    </div>
  );
}

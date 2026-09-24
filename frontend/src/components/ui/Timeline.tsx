import type { ReactNode } from "react";
import { format } from "date-fns";
import { Check, X, Send } from "lucide-react";

export interface TimelineStep {
  id: string;
  action: string;
  level: number;
  comments: string | null;
  at: string;
}

export function ApprovalTimeline({ submittedAt, steps, pendingLevel, totalLevels }: {
  submittedAt: string | null;
  steps: TimelineStep[];
  pendingLevel?: number;
  totalLevels: number;
}) {
  return (
    <ol className="space-y-4">
      <Item
        icon={<Send size={11} />}
        tone="bg-muted text-fg-muted"
        title="Submitted"
        time={submittedAt}
        last={steps.length === 0 && pendingLevel === undefined}
      />
      {steps.map((s, i) => {
        const approved = s.action.includes("APPROVE");
        const cancel = s.action.includes("CANCEL");
        return (
          <Item
            key={s.id}
            icon={approved ? <Check size={11} /> : <X size={11} />}
            tone={approved ? "bg-success/15 text-success" : "bg-danger/15 text-danger"}
            title={`${cancel ? "Cancellation " : ""}${approved ? "approved" : "rejected"} · level ${s.level}${totalLevels > 1 ? ` of ${totalLevels}` : ""}`}
            time={s.at}
            comment={s.comments}
            last={i === steps.length - 1 && pendingLevel === undefined}
          />
        );
      })}
      {pendingLevel !== undefined && (
        <Item
          icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />}
          tone="border border-dashed border-warning/60 text-warning"
          title={`Awaiting level ${pendingLevel}${totalLevels > 1 ? ` of ${totalLevels}` : ""} approval`}
          time={null}
          last
        />
      )}
    </ol>
  );
}

function Item({ icon, tone, title, time, comment, last }: {
  icon: ReactNode;
  tone: string;
  title: string;
  time: string | null;
  comment?: string | null;
  last?: boolean;
}) {
  return (
    <li className="relative flex gap-3">
      {!last && <span className="absolute left-[11px] top-7 h-[calc(100%-4px)] w-px bg-line" aria-hidden />}
      <span className={`relative grid h-6 w-6 shrink-0 place-items-center rounded-full ${tone}`}>{icon}</span>
      <div className="min-w-0 pt-0.5">
        <p className="text-[13px] font-medium text-fg">{title.charAt(0).toUpperCase() + title.slice(1)}</p>
        {time && <p className="text-xs text-fg-subtle">{format(new Date(time), "d MMM yyyy, hh:mm a")}</p>}
        {comment && <p className="mt-1.5 rounded-lg bg-muted px-3 py-2 text-[13px] text-fg-muted">“{comment}”</p>}
      </div>
    </li>
  );
}

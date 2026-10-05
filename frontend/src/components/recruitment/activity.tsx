import { useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { Dialog } from "../ui/Overlay";
import type { RecruitmentEvent, Stage } from "../../api/recruitment";
import { STAGE_CATEGORIES } from "./meta";
import { describeEvent } from "./events";

export function ActivityList({ events, empty = "No activity yet." }: { events: RecruitmentEvent[]; empty?: string }) {
  if (!events.length) return <p className="py-6 text-center text-[13px] text-fg-subtle">{empty}</p>;
  return (
    <ol className="relative space-y-4 before:absolute before:bottom-2 before:left-[13px] before:top-2 before:w-px before:bg-line">
      {events.map((e) => {
        const { icon: Icon, tone, text, body } = describeEvent(e);
        return (
          <li key={e.id} className="relative flex gap-3">
            <span className={`relative z-[1] grid h-7 w-7 shrink-0 place-items-center rounded-full border border-line bg-surface ${tone}`}>
              <Icon size={13} />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="text-[13px] text-fg-muted">
                <span className="font-medium text-fg">{e.actor_name ?? "Someone"}</span> {text}
              </p>
              {body && (
                <p className={`mt-1 whitespace-pre-line rounded-lg ${e.action === "NOTE" ? "border border-line bg-panel px-3 py-2 text-fg" : "text-fg-subtle"} text-[13px]`}>{body}</p>
              )}
              <p className="mt-0.5 text-[11px] text-fg-subtle" title={format(new Date(e.created_at), "d MMM yyyy, h:mm a")}>
                {formatDistanceToNow(new Date(e.created_at), { addSuffix: true })}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Asks for the reason a rejection / withdrawal needs before the move happens. */
export function MoveReasonDialog({ stage, candidateName, onCancel, onConfirm, pending }: {
  stage: Stage | null;
  candidateName: string;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
  pending?: boolean;
}) {
  const [reason, setReason] = useState("");
  const [lastStage, setLastStage] = useState<string | null>(null);
  if ((stage?.id ?? null) !== lastStage) {
    setLastStage(stage?.id ?? null);
    setReason("");
  }
  return (
    <Dialog open={!!stage} onClose={onCancel}>
      <form onSubmit={(e) => { e.preventDefault(); if (reason.trim()) onConfirm(reason.trim()); }}>
        <div className="space-y-3 p-6">
          <div>
            <h3 className="text-[15px] font-semibold text-fg">Move {candidateName} to {stage?.name}</h3>
            <p className="mt-0.5 text-[13px] text-fg-muted">
              {stage ? STAGE_CATEGORIES[stage.category].hint : ""}. The reason is kept in the candidate’s history.
            </p>
          </div>
          <textarea className="input" rows={3} maxLength={500} autoFocus data-autofocus
            placeholder={stage?.category === "WITHDRAWN" ? "e.g. Accepted another offer" : "e.g. Not enough system design depth"}
            value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div className="flex justify-end gap-2 border-t border-line bg-panel px-6 py-3.5">
          <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn-danger" disabled={!reason.trim() || pending}>{pending ? "Moving…" : "Move candidate"}</button>
        </div>
      </form>
    </Dialog>
  );
}

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { personnelActionsApi, rejoinApi } from "../../api/people";
import type { PersonnelActionListItem } from "../../api/people";
import { formatDateOnly } from "../../lib/dates";
import { ConfirmDialog } from "../ui/Overlay";
import { Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { reasonLabel } from "../../lib/personnelActions";
import { MODE_LABEL } from "../../lib/rejoin";

const LABEL: Record<string, string> = {
  HIRE: "Placed in a department", REHIRE: "Rehired", TRANSFER: "Transfer", PROMOTION: "Promotion",
  DEMOTION: "Demotion", CONFIRM: "Confirmed", EXTEND_PROBATION: "Probation extended",
  PLACE_ON_NOTICE: "Notice started", SEPARATION: "Separation", CHANGE_MANAGER: "Manager change",
  CHANGE_GRADE: "Grade change", CHANGE_COST_CENTRE: "Cost centre change", CHANGE_JOB: "Designation change",
};

const STATUS: Record<string, { label: string; tone: string }> = {
  APPLIED: { label: "Done", tone: "badge-neutral" },
  SCHEDULED: { label: "Scheduled", tone: "badge-info" },
  FAILED: { label: "Couldn’t apply", tone: "badge-danger" },
  CANCELLED: { label: "Cancelled", tone: "badge-neutral" },
};

function detail(a: PersonnelActionListItem): string | null {
  const c = a.changes ?? {};
  if (a.type === "EXTEND_PROBATION" && c.probation_extended_until) return `Until ${formatDateOnly(c.probation_extended_until)}`;
  if (a.type === "PLACE_ON_NOTICE" && c.expected_last_working_day) return `Expected last day ${formatDateOnly(c.expected_last_working_day)}`;
  if (a.type === "SEPARATION" && c.last_working_day) return `Last working day ${formatDateOnly(c.last_working_day)}`;
  return null;
}

/** An employee's personnel actions, newest first; scheduled ones can be cancelled before they apply. */
export function PersonnelHistory({ employmentId, canCancel }: { employmentId: string; canCancel: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [cancelling, setCancelling] = useState<PersonnelActionListItem | null>(null);
  const actions = useQuery({ queryKey: ["personnel-actions", employmentId], queryFn: () => personnelActionsApi.list(employmentId) });

  const cancel = useMutation({
    mutationFn: (id: string) => personnelActionsApi.cancel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["personnel-actions", employmentId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success("Scheduled change cancelled");
      setCancelling(null);
    },
    onError: (e) => toast.error("Couldn’t cancel the change", errorMessage(e)),
  });

  const history = useQuery({ queryKey: ["employment-history", employmentId], queryFn: () => rejoinApi.history(employmentId), retry: false });

  if (actions.isPending) return <Skeleton className="h-24 rounded-xl" />;
  if (actions.isError || !actions.data?.length) return null;

  const spells = history.data?.spells ?? [];

  return (
    <div className="space-y-4">
      {spells.length > 1 && (
        <div data-testid="employment-stints">
          <p className="eyebrow mb-2">Time with the company</p>
          <ul className="divide-y divide-line rounded-xl border border-line">
            {spells.map((sp) => (
              <li key={sp.spell_no} className="px-4 py-2.5 text-[13px]">
                <p className="font-medium text-fg">
                  {formatDateOnly(sp.joined_on)} – {sp.left_on ? formatDateOnly(sp.left_on) : "now"}
                  {sp.exit_reason && <span className="font-normal text-fg-subtle"> · left: {reasonLabel(sp.exit_reason)}</span>}
                </p>
                {sp.rejoin && (
                  <p className="text-xs text-fg-subtle">
                    Rejoined — {MODE_LABEL[sp.rejoin.mode].toLowerCase()}
                    {sp.rejoin.reason ? ` · ${sp.rejoin.reason}` : ""}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
      <p className="eyebrow mb-2">Employment changes</p>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {actions.data.slice(0, 8).map((a) => {
          const status = STATUS[a.status] ?? { label: a.status, tone: "badge-neutral" };
          const extra = [reasonLabel(a.reason_code), detail(a)].filter(Boolean).join(" · ");
          return (
            <li key={a.id} className="flex items-start gap-3 px-4 py-2.5 text-[13px]">
              <span className="w-24 shrink-0 tabular-nums text-fg-subtle">{formatDateOnly(a.effective_date)}</span>
              <div className="min-w-0 flex-1">
                <p className="font-medium text-fg">{LABEL[a.type] ?? a.type}</p>
                {extra && <p className="truncate text-xs text-fg-subtle">{extra}</p>}
                {a.status === "FAILED" && a.failure_reason && <p className="text-xs text-danger">{a.failure_reason}</p>}
              </div>
              <span className={`badge ${status.tone}`}>{status.label}</span>
              {canCancel && (a.status === "SCHEDULED" || a.status === "FAILED") && (
                <button type="button" className="btn-ghost btn-sm" onClick={() => setCancelling(a)}>Cancel</button>
              )}
            </li>
          );
        })}
      </ul>
      </div>
      <ConfirmDialog
        open={cancelling !== null}
        onClose={() => setCancelling(null)}
        onConfirm={() => cancelling && cancel.mutate(cancelling.id)}
        loading={cancel.isPending}
        title={cancelling ? `Cancel the scheduled ${(LABEL[cancelling.type] ?? cancelling.type).toLowerCase()}?` : "Cancel change?"}
        description={cancelling ? `It was due on ${formatDateOnly(cancelling.effective_date)} and will not apply.` : undefined}
        confirmLabel="Cancel change"
      />
    </div>
  );
}

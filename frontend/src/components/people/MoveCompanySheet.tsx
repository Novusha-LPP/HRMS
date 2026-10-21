import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { companyTransferApi } from "../../api/people";
import { orgApi } from "../../api/org";
import { useAuth } from "../../context/AuthContext";
import { Sheet } from "../ui/Overlay";
import { Notice } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { UsageHelpButton } from "../ui/UsageHelpButton";
import { PlacementFields } from "./PlacementFields";
import type { PlacementValues } from "./PlacementFields";
import { days } from "../../lib/rejoin";

interface Subject { id: string; name: string; legalEntityId?: string }

/** Move someone to another company of the group: ends the job here and starts one there. */
export function MoveCompanySheet({ row, onClose }: { row: Subject | null; onClose: () => void }) {
  return (
    <Sheet
      open={!!row}
      onClose={onClose}
      title={row ? `Move to another company — ${row.name}` : "Move to another company"}
      description="Ends their employment in this company and starts a new one in the other, on the same day. Each company keeps its own attendance, payroll and history."
      footer={<>
        <button className="btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn-primary" type="submit" form="move-company">Move</button>
      </>}
    >
      {row && <MoveForm key={row.id} row={row} onDone={onClose} />}
    </Sheet>
  );
}

function MoveForm({ row, onDone }: { row: Subject; onDone: () => void }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const today = format(new Date(), "yyyy-MM-dd");
  const others = (user?.legalEntities ?? []).filter((l) => l.id !== row.legalEntityId);
  const [entity, setEntity] = useState(others[0]?.id ?? "");
  const [date, setDate] = useState(today);
  const [mode, setMode] = useState<"CARRY" | "SETTLE">("CARRY");
  const [number, setNumber] = useState("");
  const [reason, setReason] = useState("");
  const [placement, setPlacement] = useState<PlacementValues>({ orgUnitId: "", jobId: "", locationId: "", managerEmploymentId: "" });

  const schemes = useQuery({ queryKey: ["employee-id-schemes"], queryFn: () => orgApi.listEmployeeIdSchemes() });
  const hasScheme = (schemes.data ?? []).some((s) => s.legal_entity_id === entity || !s.legal_entity_id);
  const preview = useQuery({
    queryKey: ["transfer-preview", row.id, entity, date, mode],
    queryFn: () => companyTransferApi.preview({ employment_id: row.id, legal_entity_id: entity, effective_date: date, leave_mode: mode }),
    enabled: !!entity && !!date,
    retry: false,
  });

  const move = useMutation({
    mutationFn: () => companyTransferApi.transfer({
      employment_id: row.id, legal_entity_id: entity, effective_date: date, leave_mode: mode,
      placement: {
        org_unit_id: placement.orgUnitId, location_id: placement.locationId, job_id: placement.jobId,
        manager_employment_id: placement.managerEmploymentId || undefined,
      },
      employee_number: number.trim() || undefined,
      reason: reason.trim() || undefined,
    }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success("Moved to the other company", `${row.name} · new employee ID ${r.employee_number}`);
      onDone();
    },
    onError: (e) => toast.error("Couldn’t move them", errorMessage(e)),
  });

  const problems: string[] = [];
  if (!entity) problems.push("Choose the company they are moving to.");
  if (!placement.orgUnitId || !placement.jobId || !placement.locationId) problems.push("Choose a department, designation and location in the new company.");
  if (!number.trim() && !hasScheme) problems.push("Enter an employee ID for the new company.");
  if (preview.data && !preview.data.can_proceed) problems.push(...preview.data.blocked);
  const [tried, setTried] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!problems.length && !move.isPending) move.mutate();
  };

  if (others.length === 0) return <Notice tone="info" title="No other company">Add another company first.</Notice>;

  return (
    <form id="move-company" onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="mc-entity">Move to</label>
          <select id="mc-entity" className="input" value={entity} onChange={(e) => { setEntity(e.target.value); setPlacement({ orgUnitId: "", jobId: "", locationId: "", managerEmploymentId: "" }); }}>
            {others.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="mc-date">Moves on</label>
          <input id="mc-date" type="date" className="input" max={today} value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
      </div>
      {entity && (
        <PlacementFields legalEntityId={entity} values={placement} onChange={(v) => setPlacement((p) => ({ ...p, ...v }))} excludeEmploymentId={row.id} />
      )}
      <div>
        <label className="label" htmlFor="mc-number">Employee ID in the new company {hasScheme && <span className="font-normal text-fg-subtle">(optional — auto-generated)</span>}</label>
        <input id="mc-number" className="input font-mono" value={number} onChange={(e) => setNumber(e.target.value)} />
      </div>
      <fieldset className="space-y-2 rounded-xl border border-line p-4" data-testid="move-leave">
        <legend className="px-1 text-sm font-semibold text-fg">Leave and service <UsageHelpButton topic="company-transfer" iconOnly /></legend>
        <label className="flex items-start gap-2 text-[13px]">
          <input type="radio" name="move-mode" checked={mode === "CARRY"} onChange={() => setMode("CARRY")} />
          <span><span className="font-medium text-fg">Carry over</span><span className="block text-xs text-fg-muted">Unused leave moves with them and their service carries on.</span></span>
        </label>
        <label className="flex items-start gap-2 text-[13px]">
          <input type="radio" name="move-mode" checked={mode === "SETTLE"} onChange={() => setMode("SETTLE")} />
          <span><span className="font-medium text-fg">Settle here</span><span className="block text-xs text-fg-muted">This company&apos;s rules for leavers apply and they start with no leave.</span></span>
        </label>
        {preview.data && preview.data.leave.length > 0 && (
          <ul className="text-[13px] text-fg-muted">
            {preview.data.leave.map((l) => <li key={l.leave_type_id}>{l.leave_type_name}: {days(l.days)} carried over</li>)}
          </ul>
        )}
        {preview.data?.warnings.map((w) => <p key={w} className="text-xs text-fg-subtle">{w}</p>)}
      </fieldset>
      <div>
        <label className="label" htmlFor="mc-reason">Reason <span className="font-normal text-fg-subtle">(optional)</span></label>
        <input id="mc-reason" className="input" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
      </div>
      {tried && problems.length > 0 && <ul className="space-y-1 text-xs text-danger" role="alert">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {move.isPending && <p className="text-xs text-fg-subtle">Moving…</p>}
    </form>
  );
}

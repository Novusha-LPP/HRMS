import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { approvalsApi } from "../../api/approvals";
import type { ApprovalFlow, RequestType } from "../../api/approvals";
import { EmptyState, Notice, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";
import { UsageHelpButton } from "../ui/UsageHelpButton";

const TYPES: { type: RequestType; title: string }[] = [
  { type: "LEAVE", title: "Leave" }, { type: "LEAVE_CANCELLATION", title: "Leave cancellation" },
  { type: "CORRECTION", title: "Attendance correction" }, { type: "OVERTIME", title: "Overtime" },
  { type: "JOB_REQUISITION", title: "Job openings they raise" },
  { type: "FIELD_OVERRIDE", title: "HR changes to fields their ERP manages" },
];

function WorkflowChoice({ employmentId, type, title, flows, assigned, version, canManage, employeeCompanyId }: {
  employmentId: string; type: RequestType; title: string; flows: ApprovalFlow[];
  assigned: ApprovalFlow | null; version: number; canManage: boolean; employeeCompanyId?: string | null;
}) {
  const [selected, setSelected] = useState(assigned?.id ?? "");
  const toast = useToast();
  const qc = useQueryClient();
  const save = useMutation({ mutationFn: () => approvalsApi.assignEmployeeFlow(employmentId, type, selected || null, version),
    onSuccess: (data) => { qc.setQueryData(["employee-approval-flows", employmentId], data); toast.success(`${title} workflow saved`); },
    onError: (e) => toast.error("Couldn’t assign workflow", errorMessage(e)),
  });
  const options = flows.filter((f) =>
    f.request_type === type &&
    f.enabled &&
    (!f.legal_entity_id || !employeeCompanyId || f.legal_entity_id === employeeCompanyId)
  );
  const chosen = options.find((f) => f.id === selected) ?? (assigned?.id === selected ? assigned : null);
  return <section className="rounded-xl border border-line p-4 space-y-3">
    <label className="label block" htmlFor={`employee-flow-${type}`}>{title}</label>
    <div className="flex flex-wrap gap-2"><select id={`employee-flow-${type}`} className="input flex-1 min-w-48" value={selected} disabled={!canManage || save.isPending} onChange={(e) => setSelected(e.target.value)}>
      <option value="">No configured workflow</option>
      {assigned && !options.some((f) => f.id === assigned.id) && <option value={assigned.id}>{assigned.name}{!assigned.enabled ? " · Disabled" : " · Existing workflow"}</option>}
      {options.map((flow) => <option key={flow.id} value={flow.id}>{flow.name}{!flow.legal_entity_id ? " · Global" : ""}</option>)}
    </select>{canManage && <button className="btn-primary btn-sm" disabled={save.isPending || selected === (assigned?.id ?? "")} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save"}</button>}</div>
    {chosen ? <ol className="flex flex-wrap gap-2">{chosen.steps.map((step, i) => <li key={step.id ?? i} className="badge badge-neutral">{i + 1}. {step.name}</li>)}</ol> : <p className="text-xs text-fg-subtle">No workflow selected. This request type uses its existing approval policy.</p>}
  </section>;
}

export function EmployeeWorkflowSection({ employmentId, legalEntityId }: { employmentId: string; legalEntityId?: string }) {
  const selection = useQuery({ queryKey: ["employee-approval-flows", employmentId], queryFn: () => approvalsApi.employeeFlows(employmentId) });
  const flows = useQuery({ queryKey: ["approval-flows"], queryFn: approvalsApi.flows });
  if (selection.isPending || flows.isPending) return <Skeleton className="h-64" />;
  if (selection.isError || flows.isError) return <Notice title="Couldn’t load approval workflows" action={<button className="btn-secondary btn-sm" onClick={() => { selection.refetch(); flows.refetch(); }}>Retry</button>}>Reload before editing the employee’s selection.</Notice>;
  const employeeCompanyId = selection.data.legal_entity_id ?? legalEntityId ?? null;
  return <div className="space-y-4">
    <div className="flex flex-wrap justify-between gap-3"><div><h3 className="card-title">Employee’s approval workflows</h3><p className="card-desc">Choose who handles this employee’s requests. Their team and department do not change these selections.</p></div><UsageHelpButton topic="approvals" /></div>
    {!selection.data.can_manage && <Notice title="Managed by HR/admin">HR/admin assigns workflows for HODs, PMs, and team leads, or employees outside your management scope.</Notice>}
    {!flows.data.length && <EmptyState title="Create a workflow first" description="Define its stages and approvers, then return here to select it." action={<Link className="btn-secondary" to="/approval-flows">Open approval flows</Link>} />}
    {TYPES.map(({ type, title }) => {
      const assignment = selection.data.assignments.find((a) => a.request_type === type);
      return <WorkflowChoice key={`${type}:${assignment?.version ?? 0}`} employmentId={employmentId} type={type} title={title} flows={flows.data} assigned={assignment?.flow ?? null} version={assignment?.version ?? 0} canManage={selection.data.can_manage} employeeCompanyId={employeeCompanyId} />;
    })}
  </div>;
}

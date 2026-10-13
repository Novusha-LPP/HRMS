import { api } from "./client";

export type RequestType = "LEAVE" | "LEAVE_CANCELLATION" | "CORRECTION" | "OVERTIME" | "JOB_REQUISITION" | "FIELD_OVERRIDE";
export interface ApprovalStep { id?: string; name: string; approver_ids: string[]; approver_source?: "PEOPLE" | "TEAM_LEAD" | "TEAM_PM"; }
export interface ApprovalFlow {
  id: string; name: string; request_type: RequestType; org_unit_id: string | null;
  reusable?: boolean; can_manage?: boolean; employment_id?: string | null; enabled: boolean; version: number; steps: ApprovalStep[];
}
export interface EmployeeFlowSelection {
  can_manage: boolean;
  assignments: { request_type: RequestType; version: number; flow: ApprovalFlow | null }[];
}
export interface ApprovalRequest {
  approval_mode?: "FLOW" | "POLICY";
  id: string; flow_id: string | null; flow_name: string; flow_version: number;
  request_type: RequestType; request_id: string; employment_id: string;
  employee_name: string; employee_number: string; request: Record<string, unknown>;
  steps: ApprovalStep[]; current_level: number; status: string; can_act: boolean;
  delegable_levels: number[]; can_manage_flow: boolean;
  history?: { action: string; actor_id: string | null; actor_name: string; details: Record<string, unknown>; created_at: string }[];
}
export interface Delegation {
  id: string; instance_id: string | null; original_user_id: string; delegate_user_id: string;
  valid_from: string; valid_until: string; reason: string; revoked_at: string | null; created_by: string;
}
export const approvalsApi = {
  employeeFlows: (id: string) => api.get<EmployeeFlowSelection>(`/v1/approvals/employees/${id}/flows`),
  assignEmployeeFlow: (id: string, type: RequestType, flowId: string | null, version: number) => api.put<EmployeeFlowSelection>(`/v1/approvals/employees/${id}/flows/${type}`, { flow_id: flowId, version }),
  flows: () => api.get<ApprovalFlow[]>("/v1/approvals/flows"),
  saveFlow: (body: Omit<ApprovalFlow, "id" | "version"> & { version?: number }, id?: string) =>
    id ? api.put<ApprovalFlow>(`/v1/approvals/flows/${id}`, body) : api.post<ApprovalFlow>("/v1/approvals/flows", body),
  directory: (instanceId?: string) => api.get<{ id: string; name: string; employment_id: string | null }[]>(`/v1/approvals/directory${instanceId ? `?instance_id=${instanceId}` : ""}`),
  inbox: () => api.get<ApprovalRequest[]>("/v1/approvals/inbox"),
  detail: (id: string) => api.get<ApprovalRequest>(`/v1/approvals/requests/${id}`),
  decide: (id: string, action: "APPROVE" | "REJECT", comments: string) =>
    api.post<ApprovalRequest>(`/v1/approvals/requests/${id}/decision`, { action, comments }),
  delegations: (id: string) => api.get<Delegation[]>(`/v1/approvals/delegations?instance_id=${id}`),
  delegate: (body: { instance_id: string; level: number; original_user_id: string; delegate_user_id: string;
    flow_wide: boolean; valid_from: string; valid_until: string; reason: string }) =>
    api.post<Delegation>("/v1/approvals/delegations", body),
  revoke: (id: string) => api.post<Delegation>(`/v1/approvals/delegations/${id}/revoke`, {}),
};

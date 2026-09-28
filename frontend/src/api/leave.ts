import { api } from "./client";

export interface LeaveType {
  id: string;
  name: string;
  code: string;
  days_per_year: number;
  carry_forward: boolean;
  max_carry_forward_days: number | null;
  requires_approval: boolean;
  approval_levels: number;
  cancel_requires_approval: boolean;
  cancel_approval_levels: number;
  min_days_per_application: number;
  max_days_per_application: number | null;
  advance_notice_days: number;
  requires_document: boolean;
  is_paid: boolean;
  is_active: boolean;
  color: string;
  is_comp_off: boolean;
  encashable: boolean;
  accrual_enabled: boolean;
}

export interface Holiday {
  id: string;
  holiday_date: string;
  name: string;
  legal_entity_id: string | null;
  is_optional: boolean;
}

export interface CompOffGrant {
  id: string;
  employment_id: string;
  work_date: string;
  days_granted: number;
  notes: string | null;
  granted_by: string | null;
  recorded_at: string;
}

export interface LeaveEncashment {
  id: string;
  employment_id: string;
  leave_type_id: string;
  leave_type_name: string;
  days: number;
  effective_date: string;
  notes: string | null;
  processed_by: string | null;
  recorded_at: string;
}

export interface AccrualRunResult {
  period: string;
  balances_credited: number;
  days_credited_total: number;
}

export interface LeaveBalance {
  id: string;
  employment_id: string;
  leave_type_id: string;
  leave_type_name: string;
  leave_type_code: string;
  year: number;
  allocated_days: number;
  carry_forward_days: number;
  used_days: number;
  pending_days: number;
  available_days: number;
  color: string;
}

export interface LeaveApprovalAction {
  id: string;
  application_id: string;
  action_type: string;
  level: number;
  approver_employment_id: string | null;
  comments: string | null;
  actioned_at: string;
}

export interface LeaveApplication {
  id: string;
  employment_id: string;
  leave_type_id: string;
  leave_type_name: string;
  leave_type_code: string;
  leave_type_color: string;
  from_date: string;
  to_date: string;
  days_requested: number;
  half_day_option: string;
  reason: string | null;
  status: string;
  current_level: number;
  total_levels: number;
  applied_at: string | null;
  cancel_reason: string | null;
  cancel_requested_at: string | null;
  approval_history: LeaveApprovalAction[];
}

export const leaveApi = {
  listTypes: () => api.get<LeaveType[]>("/v1/leave/types"),
  createType: (body: Partial<LeaveType>) => api.post<LeaveType>("/v1/leave/types", body),
  updateType: (id: string, body: Partial<LeaveType>) => api.patch<LeaveType>(`/v1/leave/types/${id}`, body),

  getBalances: (employmentId: string, year?: number) => {
    const q = year ? `?employment_id=${employmentId}&year=${year}` : `?employment_id=${employmentId}`;
    return api.get<LeaveBalance[]>(`/v1/leave/balances${q}`);
  },
  initBalances: (employmentId: string, year: number) =>
    api.post<{ created: number }>(`/v1/leave/balances/init?employment_id=${employmentId}&year=${year}`, {}),

  listApplications: (employmentId?: string, status?: string) => {
    const params = new URLSearchParams();
    if (employmentId) params.set("employment_id", employmentId);
    if (status) params.set("status", status);
    return api.get<LeaveApplication[]>(`/v1/leave/applications?${params}`);
  },
  createApplication: (employmentId: string, body: {
    leave_type_id: string;
    from_date: string;
    to_date: string;
    half_day_option?: string;
    document_id?: string;
    reason?: string;
  }) => api.post<LeaveApplication>(`/v1/leave/applications?employment_id=${employmentId}`, body),

  submit: (appId: string, employmentId: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/submit?employment_id=${employmentId}`, {}),

  // The approver is always the signed-in account (from the token) — no id is passed.
  approve: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/approve`, { action: "APPROVE", comments }),

  reject: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/reject`, { action: "REJECT", comments }),

  cancel: (appId: string, employmentId: string, cancelReason?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/cancel?employment_id=${employmentId}`, { cancel_reason: cancelReason }),

  cancelApprove: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/cancel-approve`, { action: "APPROVE", comments }),

  cancelReject: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/cancel-reject`, { action: "REJECT", comments }),

  listHolidays: (year?: number) => api.get<Holiday[]>(`/v1/time/holidays${year ? `?year=${year}` : ""}`),
  createHoliday: (body: { holiday_date: string; name: string; is_optional?: boolean }) =>
    api.post<Holiday>("/v1/time/holidays", body),
  deleteHoliday: (id: string) => api.delete(`/v1/time/holidays/${id}`),

  grantCompOff: (body: { employment_id: string; work_date: string; days_granted?: number; notes?: string }) =>
    api.post<CompOffGrant>("/v1/leave/comp-off", body),

  encash: (body: { employment_id: string; leave_type_id: string; days: number; notes?: string }) =>
    api.post<LeaveEncashment>("/v1/leave/encashment", body),

  runAccrual: (period?: string) =>
    api.post<AccrualRunResult>(`/v1/leave/accrual/run${period ? `?period=${period}` : ""}`, {}),
};

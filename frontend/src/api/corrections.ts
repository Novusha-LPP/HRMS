import { api } from "./client";

export interface CorrectionApprovalAction {
  id: string;
  correction_id: string;
  action: string;
  level: number;
  approver_employment_id: string | null;
  comments: string | null;
  actioned_at: string;
}

export interface AttendanceCorrection {
  id: string;
  employment_id: string;
  work_date: string;
  correction_type: string;
  requested_punch_in: string | null;
  requested_punch_out: string | null;
  reason: string;
  status: string;
  current_level: number;
  total_levels: number;
  submitted_at: string | null;
  approval_history: CorrectionApprovalAction[];
}

export const correctionsApi = {
  list: (employmentId?: string, status?: string) => {
    const params = new URLSearchParams();
    if (employmentId) params.set("employment_id", employmentId);
    if (status) params.set("status", status);
    return api.get<AttendanceCorrection[]>(`/v1/corrections?${params}`);
  },

  create: (employmentId: string, body: {
    work_date: string;
    correction_type: string;
    requested_punch_in?: string;
    requested_punch_out?: string;
    reason: string;
  }) => api.post<AttendanceCorrection>(`/v1/corrections?employment_id=${employmentId}`, body),

  approve: (id: string, approverEmpId: string, comments?: string) =>
    api.post<AttendanceCorrection>(`/v1/corrections/${id}/approve?approver_employment_id=${approverEmpId}`, { action: "APPROVE", comments }),

  reject: (id: string, approverEmpId: string, comments?: string) =>
    api.post<AttendanceCorrection>(`/v1/corrections/${id}/reject?approver_employment_id=${approverEmpId}`, { action: "REJECT", comments }),

  cancel: (id: string) =>
    api.post<AttendanceCorrection>(`/v1/corrections/${id}/cancel`, {}),
};

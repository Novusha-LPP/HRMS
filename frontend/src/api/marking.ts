import { api } from "./client";
import type { LeaveApplication } from "./leave";

/** What a marker records for a day (backend time/marking.py). */
export type MarkStatus = "PRESENT" | "ABSENT";
/** What someone may do with an attendance group's daily sheet. */
export type GroupAccessLevel = "VIEW" | "MARK";

export interface MarkInfo {
  /** PRESENT / ABSENT, or null when the mark was cleared. */
  status: MarkStatus | null;
  punch_in: string | null;
  punch_out: string | null;
  remark: string | null;
  marked_by: string | null;
  marked_at: string;
  source: "MANUAL" | "INTEGRATION";
}

export interface MarkingRow {
  employment_id: string;
  employee_number: string | null;
  name: string;
  company: string;
  department: string | null;
  group_id: string;
  group_name: string;
  access: GroupAccessLevel;
  /** PRESENT / ABSENT (marked), NOT_MARKED, ON_LEAVE, HOLIDAY, WEEKEND, LATE (from times)… */
  status: string;
  is_off_day: boolean;
  holiday_name: string | null;
  leave_type: string | null;
  /** The person's own punches: the day is computed from them and can't be marked. */
  has_punches: boolean;
  /** Times a marker entered. */
  punch_in: string | null;
  punch_out: string | null;
  worked_minutes: number;
  late_by_minutes: number;
  /** The person's policy clock: times are entered and shown on it. */
  timezone: string;
  is_locked: boolean;
  can_mark: boolean;
  blocked_reason: string | null;
  mark: MarkInfo | null;
}

export interface MarkingResponse {
  work_date: string;
  rows: MarkingRow[];
  counts: Record<string, number>;
}

export interface MarkingResult {
  work_date: string;
  changed: number;
  unchanged: number;
  rows: MarkingRow[];
}

export interface MarkingLeaveType {
  id: string;
  name: string;
  code: string;
  is_paid: boolean;
}

export interface MarkEntry {
  employment_id: string;
  /** null clears the mark: the day goes back to "Not marked". */
  status: MarkStatus | null;
  /** "HH:MM" on the person's clock, only with PRESENT. Out not after in = next morning. */
  punch_in?: string;
  punch_out?: string;
  remark?: string;
}

export interface MarkingLeaveRequest {
  employment_id: string;
  leave_type_id: string;
  from_date: string;
  to_date: string;
  half_day_option?: "NONE" | "FIRST_HALF" | "SECOND_HALF";
  reason?: string;
}

export interface AttendanceGroup {
  id: string;
  name: string;
  description: string | null;
  legal_entity_id: string | null;
  company: string | null;
  member_count: number;
  my_access: GroupAccessLevel;
  can_manage: boolean;
}

export interface GroupMember {
  employment_id: string;
  employee_number: string | null;
  name: string;
  company: string;
  department: string | null;
  effective_from: string;
}

export interface GroupAccessEntry {
  user_account_id: string;
  name: string;
  email: string | null;
  access_level: GroupAccessLevel;
}

export const markingApi = {
  day: (workDate: string, group?: string, company?: string) => {
    const query = new URLSearchParams({ work_date: workDate });
    if (group) query.set("group_id", group);
    if (company) query.set("legal_entity_id", company);
    return api.get<MarkingResponse>(`/v1/time/marking?${query}`);
  },
  /** All or nothing: one refused row refuses the save (the error names each one). */
  mark: (workDate: string, marks: MarkEntry[], remark?: string) =>
    api.put<MarkingResult>(`/v1/time/marking/${workDate}`, { marks, remark: remark || undefined }),
  leaveTypes: () => api.get<MarkingLeaveType[]>("/v1/time/marking/leave-types"),
  recordLeave: (body: MarkingLeaveRequest) =>
    api.post<LeaveApplication>("/v1/time/marking/leave", body),
};

const GROUPS = "/v1/time/attendance-groups";

export const groupsApi = {
  list: () => api.get<AttendanceGroup[]>(GROUPS),
  create: (body: { name: string; description?: string; legal_entity_id?: string }) =>
    api.post<AttendanceGroup>(GROUPS, body),
  update: (id: string, body: { name?: string; description?: string | null; legal_entity_id?: string | null }) =>
    api.patch<AttendanceGroup>(`${GROUPS}/${id}`, body),
  archive: (id: string) => api.delete<void>(`${GROUPS}/${id}`),
  members: (id: string, on?: string) =>
    api.get<GroupMember[]>(`${GROUPS}/${id}/members${on ? `?on=${on}` : ""}`),
  addMembers: (id: string, employmentIds: string[], effectiveFrom: string) =>
    api.post<GroupMember[]>(`${GROUPS}/${id}/members`, { employment_ids: employmentIds, effective_from: effectiveFrom }),
  removeMember: (id: string, employmentId: string, lastDay: string) =>
    api.delete<void>(`${GROUPS}/${id}/members/${employmentId}?last_day=${lastDay}`),
  access: (id: string) => api.get<GroupAccessEntry[]>(`${GROUPS}/${id}/access`),
  grant: (id: string, userId: string, level: GroupAccessLevel) =>
    api.put<GroupAccessEntry[]>(`${GROUPS}/${id}/access/${userId}`, { access_level: level }),
  revoke: (id: string, userId: string) => api.delete<void>(`${GROUPS}/${id}/access/${userId}`),
};

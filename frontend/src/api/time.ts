import { api, API_BASE_URL } from "./client";

export interface TodayStatus {
  employment_id: string;
  work_date: string;
  is_punched_in: boolean;
  first_punch_in: string | null;
  last_punch_out: string | null;
  effective_minutes: number;
  status: string;
  punches: Punch[];
}

export interface Punch {
  id: string;
  punch_type: "IN" | "OUT" | "BREAK_START" | "BREAK_END";
  punched_at: string;
  source: string;
  latitude: number | null;
  longitude: number | null;
  is_corrected: boolean;
}

/** INFO: extra time beyond the shift with no overtime policy — shown only, never approved or paid. */
export type OvertimeStatus = "NONE" | "PENDING" | "APPROVED" | "REJECTED" | "INFO";

export interface AttendanceDay {
  id: string;
  work_date: string;
  first_punch_in: string | null;
  last_punch_out: string | null;
  effective_minutes: number;
  late_by_minutes: number;
  status: string;
  is_locked: boolean;
  ot_minutes: number;
  ot_status: OvertimeStatus;
  ot_reviewed_by: string | null;
  ot_reviewed_at: string | null;
  ot_review_notes: string | null;
  /** Comp-off days credited for work on an off day (comp-off policy). */
  comp_off_days: number;
  /** Why HR should check the day; overtime and comp-off wait until it is reviewed. */
  review_flags: ReviewFlag[];
  needs_review: boolean;
  reviewed_at: string | null;
}

/** BREAK_NOT_ENDED: a break was never ended. LONG_DAY: over 16 h from check-in to check-out. */
export type ReviewFlag = "BREAK_NOT_ENDED" | "LONG_DAY" | "LEGACY_CONFLICT";

export const REVIEW_FLAG_LABEL: Record<ReviewFlag, string> = {
  LEGACY_CONFLICT: "Imported punches need correction",
  BREAK_NOT_ENDED: "Break never ended",
  LONG_DAY: "Over 16 hours",
};

export interface PendingOvertimeItem {
  attendance_day_id: string;
  employment_id: string;
  employee_number: string;
  name: string;
  department?: string | null;
  work_date: string;
  effective_minutes: number;
  ot_minutes: number;
  ot_status: OvertimeStatus;
}

export interface DailyEmployeeRecord {
  employment_id: string;
  employee_number: string;
  name: string;
  email?: string | null;
  department?: string | null;
  designation?: string | null;
  location?: string | null;
  status: string;
  first_punch_in?: string | null;
  last_punch_out?: string | null;
  effective_minutes: number;
  gross_minutes: number;
  break_minutes: number;
  late_by_minutes: number;
  early_departure_minutes: number;
  overtime_minutes: number;
  overtime_status: OvertimeStatus;
  comp_off_days: number;
  review_flags: ReviewFlag[];
  needs_review: boolean;
  attendance_day_id?: string | null;
  leave_type?: string | null;
  punches_count: number;
  is_currently_in: boolean;
}

export interface DailyMetrics {
  total_headcount: number;
  present_count: number;
  on_time_count: number;
  late_count: number;
  absent_count: number;
  on_leave_count: number;
  half_day_count: number;
  presence_rate: number;
  average_work_minutes: number;
  total_overtime_minutes: number;
}

export interface DepartmentAttendanceStat {
  department: string;
  total: number;
  present: number;
  late: number;
  absent: number;
  on_leave: number;
  presence_rate: number;
}

export interface HourlyArrivalStat {
  hour: string;
  count: number;
}

export interface DailyAnalysisResponse {
  snapshot_id: string;
  generated_at: string;
  total_filtered: number;
  work_date: string;
  metrics: DailyMetrics;
  department_stats: DepartmentAttendanceStat[];
  hourly_arrivals: HourlyArrivalStat[];
  employees: DailyEmployeeRecord[];
}

export interface DailyAnalysisParams {
  snapshot_id?: string;
  limit?: number;
  offset?: number;
  work_date?: string;
  department?: string;
  status?: string;
  search?: string;
}

export interface RegisterEmployee {
  employment_id: string;
  employee_number: string;
  name: string;
  department?: string | null;
}

export type RegisterPunchType = "IN" | "OUT" | "BREAK_START" | "BREAK_END";

export interface RegisterPunch {
  id: string;
  punch_type: RegisterPunchType;
  punched_at: string;
  source: string;
  is_corrected: boolean;
  correction_reason?: string | null;
}

/** One calendar day of an employee's attendance register. */
export interface RegisterDay {
  work_date: string;
  /** Stored status when the day has punches; otherwise ON_LEAVE, HOLIDAY, WEEKEND, UPCOMING or ABSENT. */
  status: string;
  is_off_day: boolean;
  holiday_name?: string | null;
  leave_type?: string | null;
  attendance_day_id?: string | null;
  first_punch_in?: string | null;
  last_punch_out?: string | null;
  effective_minutes: number;
  gross_minutes: number;
  break_minutes: number;
  late_by_minutes: number;
  early_departure_minutes: number;
  ot_minutes: number;
  ot_status: OvertimeStatus;
  comp_off_days: number;
  review_flags: ReviewFlag[];
  needs_review: boolean;
  is_locked: boolean;
  shift_start: string;
  shift_end: string;
  /** The policy's timezone: punches are shown and edited on this clock. */
  timezone: string;
  /** Policy figures behind the status, for previewing an edit. */
  policy_break_minutes: number;
  grace_late_minutes: number;
  grace_early_minutes: number;
  standard_minutes: number;
  half_day_minutes: number;
  punches: RegisterPunch[];
}

export interface RegisterResponse {
  employment_id: string;
  employee_number: string;
  name: string;
  department?: string | null;
  designation?: string | null;
  from_date: string;
  to_date: string;
  days: RegisterDay[];
}

export const timeApi = {
  /** A check-out over 16 h after check-in fails with code LONG_DAY_CONFIRM unless confirmed. */
  punch: (
    employmentId: string,
    type: "IN" | "OUT",
    lat?: number,
    lng?: number,
    confirmLongDay = false,
  ) =>
    api.post<Punch>(`/v1/time/punches?employment-id=${employmentId}`, {
      punch_type: type,
      source: "WEB",
      latitude: lat,
      longitude: lng,
      confirm_long_day: confirmLongDay,
    }),

  today: (employmentId: string, workDate?: string) =>
    api.get<TodayStatus>(
      `/v1/time/today?employment_id=${employmentId}${workDate ? `&work_date=${workDate}` : ""}`,
    ),

  attendanceDays: (employmentId: string, from: string, to: string) =>
    api.get<AttendanceDay[]>(
      `/v1/time/attendance-days?employment_id=${employmentId}&from_date=${from}&to_date=${to}`,
    ),

  dailyAnalysis: (params?: DailyAnalysisParams) => {
    const q = new URLSearchParams();
    if (params?.snapshot_id) q.set("snapshot_id", params.snapshot_id);
    if (params?.limit !== undefined) q.set("limit", String(params.limit));
    if (params?.offset !== undefined) q.set("offset", String(params.offset));
    if (params?.work_date) q.append("work_date", params.work_date);
    if (params?.department) q.append("department", params.department);
    if (params?.status) q.append("status", params.status);
    if (params?.search) q.append("search", params.search);
    const qs = q.toString();
    return api.get<DailyAnalysisResponse>(`/v1/time/daily-analysis${qs ? `?${qs}` : ""}`);
  },

  exportDailyAnalysis: (params: DailyAnalysisParams & { snapshot_id: string; work_date: string }) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) query.set(key, String(value));
    }
    // Content-Disposition performs the download; the HttpOnly cookie authenticates it.
    const link = document.createElement("a");
    link.href = `${API_BASE_URL}/v1/time/daily-analysis/export?${query}`;
    link.target = "_blank";
    link.rel = "noopener";
    link.click();
  },

  pendingOvertime: (from?: string, to?: string) => {
    const q = new URLSearchParams();
    if (from) q.append("from_date", from);
    if (to) q.append("to_date", to);
    const qs = q.toString();
    return api.get<PendingOvertimeItem[]>(`/v1/time/overtime/pending${qs ? `?${qs}` : ""}`);
  },
  reviewOvertime: (attendanceDayId: string, status: "APPROVED" | "REJECTED", notes?: string) =>
    api.patch<AttendanceDay>(`/v1/time/overtime/${attendanceDayId}`, { status, notes }),
  findEmployees: (search: string) =>
    api.get<RegisterEmployee[]>(`/v1/time/register/employees?search=${encodeURIComponent(search)}`),
  register: (employmentId: string, from: string, to: string) =>
    api.get<RegisterResponse>(`/v1/time/register/${employmentId}?from_date=${from}&to_date=${to}`),
  /** HR direct correction: the day's complete punch list (empty = absent), applied at once. */
  editDay: (
    employmentId: string,
    workDate: string,
    punches: { punch_type: RegisterPunchType; punched_at: string }[],
    reason: string,
  ) => api.put<RegisterDay>(`/v1/time/register/${employmentId}/${workDate}`, { punches, reason }),
  /** Accept a flagged day as recorded: its overtime / comp-off are then raised. */
  reviewDay: (attendanceDayId: string) =>
    api.post<AttendanceDay>(`/v1/time/attendance-days/${attendanceDayId}/review`, {}),
};

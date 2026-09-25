import { api } from "./client";

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

export type OvertimeStatus = "NONE" | "PENDING" | "APPROVED" | "REJECTED";

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
}

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
  work_date: string;
  metrics: DailyMetrics;
  department_stats: DepartmentAttendanceStat[];
  hourly_arrivals: HourlyArrivalStat[];
  employees: DailyEmployeeRecord[];
}

export interface DailyAnalysisParams {
  work_date?: string;
  department?: string;
  status?: string;
  search?: string;
}

export const timeApi = {
  punch: (employmentId: string, type: "IN" | "OUT", lat?: number, lng?: number) =>
    api.post<Punch>(`/v1/time/punches?employment-id=${employmentId}`, {
      punch_type: type,
      source: "WEB",
      latitude: lat,
      longitude: lng,
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
    if (params?.work_date) q.append("work_date", params.work_date);
    if (params?.department) q.append("department", params.department);
    if (params?.status) q.append("status", params.status);
    if (params?.search) q.append("search", params.search);
    const qs = q.toString();
    return api.get<DailyAnalysisResponse>(`/v1/time/daily-analysis${qs ? `?${qs}` : ""}`);
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
};


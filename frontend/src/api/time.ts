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

export interface AttendanceDay {
  id: string;
  work_date: string;
  first_punch_in: string | null;
  last_punch_out: string | null;
  effective_minutes: number;
  late_by_minutes: number;
  status: string;
  is_locked: boolean;
}

export const timeApi = {
  punch: (employmentId: string, type: "IN" | "OUT", lat?: number, lng?: number) =>
    api.post<Punch>(`/v1/time/punches?employment-id=${employmentId}`, {
      punch_type: type,
      source: "WEB",
      latitude: lat,
      longitude: lng,
    }),

  today: (employmentId: string) =>
    api.get<TodayStatus>(`/v1/time/today?employment_id=${employmentId}`),

  attendanceDays: (employmentId: string, from: string, to: string) =>
    api.get<AttendanceDay[]>(
      `/v1/time/attendance-days?employment_id=${employmentId}&from_date=${from}&to_date=${to}`,
    ),
};

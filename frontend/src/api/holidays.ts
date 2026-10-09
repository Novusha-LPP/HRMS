import { api } from "./client";

/** Who a calendar is for. The most specific wins: employee, then department, entity, company. */
export type CalendarTarget = "COMPANY" | "LEGAL_ENTITY" | "DEPARTMENT" | "EMPLOYEE";

export interface CalendarDay {
  id: string;
  holiday_id: string;
  holiday_date: string;
  name: string;
  holiday_type?: string | null;
  is_optional: boolean;
  /** Other calendars observing the same holiday — it is one shared row. */
  shared_with: string[];
}

export interface CalendarAssignment {
  id: string;
  target: CalendarTarget;
  target_id: string | null;
  target_name: string;
  target_detail?: string | null;
  effective_from: string;
  effective_to: string | null;
}

export interface HolidayCalendar {
  id: string;
  name: string;
  year: number;
  days: CalendarDay[];
  assignments: CalendarAssignment[];
  /** Active employees following it today. */
  people: number;
}

export interface CalendarCoverage {
  calendar_id: string | null;
  name: string;
  people: number;
}

/** A holiday on the year's holiday list, with the calendars that include it. */
export interface ListHoliday {
  id: string;
  holiday_date: string;
  name: string;
  holiday_type?: string | null;
  calendars: { id: string; name: string; is_optional: boolean }[];
}

const URL = "/v1/time/holiday-calendars";

export const holidayApi = {
  // Step 1 — the holiday list
  listHolidays: (year: number) => api.get<ListHoliday[]>(`${URL}/library?year=${year}`),
  addHoliday: (body: { holiday_date: string; name: string }) => api.post<ListHoliday>(`${URL}/library`, body),
  updateHoliday: (id: string, body: { holiday_date?: string; name?: string }) =>
    api.patch<ListHoliday>(`${URL}/library/${id}`, body),
  deleteHoliday: (id: string) => api.delete(`${URL}/library/${id}`),
  // Step 2 — calendars built from the list
  setDays: (id: string, holidays: { holiday_id: string; is_optional?: boolean }[]) =>
    api.put<HolidayCalendar>(`${URL}/${id}/days`, { holidays }),
  list: (year: number) => api.get<HolidayCalendar[]>(`${URL}?year=${year}`),
  coverage: () => api.get<CalendarCoverage[]>(`${URL}/coverage`),
  create: (body: { name: string; year: number; holiday_ids?: string[]; copy_from?: string; assign_company?: boolean }) =>
    api.post<HolidayCalendar>(URL, body),
  rename: (id: string, name: string) => api.patch<HolidayCalendar>(`${URL}/${id}`, { name }),
  archive: (id: string) => api.delete(`${URL}/${id}`),
  addDay: (id: string, body: { holiday_id?: string; holiday_date?: string; name?: string; is_optional?: boolean }) =>
    api.post<HolidayCalendar>(`${URL}/${id}/days`, body),
  updateDay: (id: string, dayId: string, body: { is_optional?: boolean; name?: string }) =>
    api.patch<HolidayCalendar>(`${URL}/${id}/days/${dayId}`, body),
  removeDay: (id: string, dayId: string) => api.delete<HolidayCalendar>(`${URL}/${id}/days/${dayId}`),
  assign: (id: string, body: { target: CalendarTarget; target_id?: string | null; effective_from?: string; replace?: boolean }) =>
    api.post<HolidayCalendar>(`${URL}/${id}/assignments`, body),
  unassign: (id: string, assignmentId: string) => api.delete<HolidayCalendar>(`${URL}/${id}/assignments/${assignmentId}`),
};

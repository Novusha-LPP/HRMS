import { api, API_BASE_URL, ApiError, getAuthToken } from "./client";
import { withRequestDeadline } from "../lib/requestDeadline";

export interface ColumnMeta {
  field: string;
  label: string;
  type: string;
  default: boolean;
  options?: string[];
}

export interface FilterMeta {
  field: string;
  label: string;
  type: string;
  ops: string[];
  options?: string[];
}

export interface ReportMeta {
  module: string;
  columns: ColumnMeta[];
  filters: FilterMeta[];
}

export interface ColumnSpec { field: string; label: string; visible: boolean; }
export interface FilterSpec { field: string; op: string; value: unknown; }

export interface ReportDef {
  id: string;
  name: string;
  description: string;
  module: string;
  columns: ColumnSpec[];
  filters: FilterSpec[];
  is_system: boolean;
  owner_type: string;
}

export interface RunResult {
  report_id: string;
  name: string;
  module: string;
  columns: ColumnSpec[];
  rows: Record<string, unknown>[];
  total_rows: number;
  truncated?: boolean;
  generated_at: string;
}

function attendanceFilename(disposition: string | null, filters: FilterSpec[]) {
  const encoded = disposition?.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1];
  let filename = disposition?.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i)?.slice(1).find(Boolean)?.trim();
  if (encoded) {
    try { filename = decodeURIComponent(encoded.trim()); } catch { /* Keep the ordinary filename. */ }
  }
  // Content-Disposition is server input; retain only a safe workbook basename.
  if (filename) {
    filename = filename.split(/[\\/]/).pop()?.replace(/[:*?"<>|]/g, "_");
    filename = Array.from(filename ?? "").filter((char) => char.charCodeAt(0) >= 32 && char.charCodeAt(0) !== 127).join("");
    if (filename && filename.length <= 180 && /\.xlsx$/i.test(filename)) return filename;
  }
  const from = filters.find((filter) => filter.field === "work_date" && filter.op === "gte")?.value;
  const to = filters.find((filter) => filter.field === "work_date" && filter.op === "lte")?.value;
  if (typeof from === "string" && typeof to === "string" && /^\d{4}-\d{2}-\d{2}$/.test(from) && /^\d{4}-\d{2}-\d{2}$/.test(to)) {
    return `AttendanceReport_${from}_to_${to}.xlsx`;
  }
  return "AttendanceReport.xlsx";
}

export const reportsApi = {
  meta: (module: string) => api.get<ReportMeta>(`/v1/reports/meta/${module}`),
  list:  (ownerType?: string) => {
    const q = ownerType ? `?owner_type=${ownerType}` : "";
    return api.get<ReportDef[]>(`/v1/reports${q}`);
  },
  get:    (id: string) => api.get<ReportDef>(`/v1/reports/${id}`),
  create: (body: Omit<ReportDef, "id" | "is_system">) => api.post<ReportDef>("/v1/reports", body),
  delete: (id: string) => api.delete(`/v1/reports/${id}`),
  run:    (id: string, filters: FilterSpec[] = [], limit = 1000) =>
    api.post<RunResult>(`/v1/reports/${id}/run`, { filters, limit }),
  exportAttendance: async (id: string, filters: FilterSpec[] = []) => {
    const session = getAuthToken();
    const { blob, filename } = await withRequestDeadline(async (signal) => {
      const response = await fetch(`${API_BASE_URL}/v1/reports/${encodeURIComponent(id)}/export-attendance`, {
        method: "POST", credentials: "include", signal,
        headers: { "Content-Type": "application/json", "X-HRMS-Session": "cookie" },
        body: JSON.stringify({ filters }),
      });
      if (session !== getAuthToken()) throw new Error("Session changed");
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        const detail = body.detail || body.error?.message;
        throw new ApiError(response.status, body.code || body.error?.code || "EXPORT_FAILED",
          typeof detail === "string" ? detail : "Couldn’t export the attendance workbook",
          body.request_id || body.error?.request_id || response.headers.get("x-request-id") || undefined);
      }
      return { blob: await response.blob(), filename: attendanceFilename(response.headers.get("Content-Disposition"), filters) };
    });
    if (session !== getAuthToken()) throw new Error("Session changed");
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  },
};

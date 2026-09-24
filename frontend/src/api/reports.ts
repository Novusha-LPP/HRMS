import { api } from "./client";

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
  generated_at: string;
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
};

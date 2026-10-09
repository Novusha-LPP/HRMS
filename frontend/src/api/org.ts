import { api } from "./client";

export interface LegalEntity {
  id: string;
  name: string;
  short_name: string | null;
  country_code: string;
  status: string;
  version: number;
  establishment_date: string | null;
  financial_year_start_month: number | null;
}

/** One edit — GET .../{id}/history. Field -> {old, new}; only fields that actually changed. */
export interface ChangeLogEntry {
  id: string;
  action: "CREATE" | "UPDATE" | "ARCHIVE";
  changes: Record<string, { old: unknown; new: unknown }>;
  changed_by: string | null;
  changed_by_name: string | null;
  changed_at: string;
}

export interface Location {
  id: string;
  name: string;
  type: string;
  city: string | null;
  state_code: string | null;
  country_code: string;
  timezone: string;
  status: string;
  version: number;
  legal_entity_id: string | null;
}

export interface OrgUnit {
  id: string;
  name: string;
  code: string | null;
  type: string;
  parent_id: string | null;
  legal_entity_id: string | null;
  department_template_id?: string | null;
  head_employment_id?: string | null;
  lead_employment_id?: string | null;
  pm_employment_id?: string | null;
  status: string;
  effective_from: string;
  effective_to: string | null;
  version: number;
}

export interface Job {
  id: string;
  title: string;
  code: string | null;
  function: string | null;
  status: string;
  version: number;
}

export type MasterStatus = "ACTIVE" | "INACTIVE";

export interface Grade {
  id: string;
  code: string;
  name: string;
  /** Rank order: lower is more junior. */
  sequence: number;
  status: string;
  version: number;
}

export interface CostCentre {
  id: string;
  code: string;
  name: string;
  status: string;
  version: number;
}

export interface Position {
  id: string;
  title: string;
  code: string | null;
  org_unit_id: string;
  org_unit_name: string | null;
  legal_entity_id: string | null;
  job_id: string | null;
  job_title: string | null;
  grade_id: string | null;
  grade_name: string | null;
  max_headcount: number | null;
  filled: number;
  vacancies: number | null;
  status: string;
  effective_from: string;
  effective_to: string | null;
  version: number;
}

export interface EmployeeIdScheme {
  id: string;
  legal_entity_id: string | null;
  legal_entity_name: string | null;
  prefix: string;
  separator: string;
  number_digits: number;
  next_number: number;
  preview: string;
}

export const orgApi = {
  listLegalEntities: () => api.get<LegalEntity[]>("/v1/org/legal-entities"),
  createLegalEntity: (body: {
    name: string; short_name?: string; country_code?: string; financial_year_start_month?: number; establishment_date?: string | null;
  }) => api.post<LegalEntity>("/v1/org/legal-entities", body),
  updateLegalEntity: (
    id: string,
    body: Partial<Pick<LegalEntity, "name" | "short_name" | "country_code" | "financial_year_start_month" | "establishment_date">>,
  ) => api.patch<LegalEntity>(`/v1/org/legal-entities/${id}`, body),
  legalEntityHistory: (id: string) => api.get<ChangeLogEntry[]>(`/v1/org/legal-entities/${id}/history`),

  listLocations: () => api.get<Location[]>("/v1/org/locations"),
  createLocation: (body: {
    name: string; type: string; legal_entity_id?: string; city?: string;
    state_code?: string; country_code?: string; timezone?: string;
  }) => api.post<Location>("/v1/org/locations", body),
  updateLocation: (
    id: string,
    body: Partial<Pick<Location, "name" | "type" | "city" | "state_code" | "country_code" | "timezone">>,
  ) => api.patch<Location>(`/v1/org/locations/${id}`, body),
  locationHistory: (id: string) => api.get<ChangeLogEntry[]>(`/v1/org/locations/${id}/history`),

  assignDepartments: (entityId: string, departmentIds: string[]) =>
    api.post<OrgUnit[]>(`/v1/org/legal-entities/${entityId}/departments`, { department_ids: departmentIds }),
  listOrgUnits: () => api.get<OrgUnit[]>("/v1/org/org-units"),
  createOrgUnit: (body: {
    name: string; type: string; code?: string; parent_id?: string;
    legal_entity_id?: string; location_id?: string; effective_from: string; head_employment_id?: string | null; lead_employment_id?: string | null; pm_employment_id?: string | null;
  }) => api.post<OrgUnit>("/v1/org/org-units", body),
  updateOrgUnit: (id: string, body: Partial<Pick<OrgUnit, "name" | "code" | "type" | "head_employment_id" | "lead_employment_id" | "pm_employment_id">>) =>
    api.patch<OrgUnit>(`/v1/org/org-units/${id}`, body),
  orgUnitHistory: (id: string) => api.get<ChangeLogEntry[]>(`/v1/org/org-units/${id}/history`),

  listJobs: () => api.get<Job[]>("/v1/org/jobs"),
  createJob: (body: { title: string; code?: string; function?: string }) =>
    api.post<Job>("/v1/org/jobs", body),
  updateJob: (id: string, body: Partial<Pick<Job, "title" | "code" | "function">>) =>
    api.patch<Job>(`/v1/org/jobs/${id}`, body),
  jobHistory: (id: string) => api.get<ChangeLogEntry[]>(`/v1/org/jobs/${id}/history`),

  listGrades: () => api.get<Grade[]>("/v1/org/grades"),
  createGrade: (body: { code: string; name: string; sequence?: number }) => api.post<Grade>("/v1/org/grades", body),
  updateGrade: (id: string, body: Partial<{ code: string; name: string; sequence: number; status: MasterStatus }>) =>
    api.patch<Grade>(`/v1/org/grades/${id}`, body),
  gradeHistory: (id: string) => api.get<ChangeLogEntry[]>(`/v1/org/grades/${id}/history`),

  listCostCentres: () => api.get<CostCentre[]>("/v1/org/cost-centres"),
  createCostCentre: (body: { code: string; name: string }) => api.post<CostCentre>("/v1/org/cost-centres", body),
  updateCostCentre: (id: string, body: Partial<{ code: string; name: string; status: MasterStatus }>) =>
    api.patch<CostCentre>(`/v1/org/cost-centres/${id}`, body),
  costCentreHistory: (id: string) => api.get<ChangeLogEntry[]>(`/v1/org/cost-centres/${id}/history`),

  listPositions: () => api.get<Position[]>("/v1/org/positions"),
  createPosition: (body: {
    title: string; org_unit_id: string; code?: string; job_id?: string; grade_id?: string;
    max_headcount?: number; effective_from?: string;
  }) => api.post<Position>("/v1/org/positions", body),
  updatePosition: (id: string, body: Partial<{
    title: string; code: string | null; job_id: string | null; grade_id: string | null;
    max_headcount: number | null; status: MasterStatus; effective_to: string | null;
  }>) => api.patch<Position>(`/v1/org/positions/${id}`, body),
  positionHistory: (id: string) => api.get<ChangeLogEntry[]>(`/v1/org/positions/${id}/history`),

  listEmployeeIdSchemes: () => api.get<EmployeeIdScheme[]>("/v1/org/employee-id-schemes"),
  createEmployeeIdScheme: (body: {
    legal_entity_id?: string; prefix: string; separator?: string; number_digits?: number; next_number?: number;
  }) => api.post<EmployeeIdScheme>("/v1/org/employee-id-schemes", body),
  updateEmployeeIdScheme: (id: string, body: Partial<Pick<EmployeeIdScheme, "prefix" | "separator" | "number_digits" | "next_number">>) =>
    api.patch<EmployeeIdScheme>(`/v1/org/employee-id-schemes/${id}`, body),
  deleteEmployeeIdScheme: (id: string) => api.delete(`/v1/org/employee-id-schemes/${id}`),
};

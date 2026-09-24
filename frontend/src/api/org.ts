import { api } from "./client";

export interface LegalEntity {
  id: string;
  name: string;
  short_name: string | null;
  country_code: string;
  status: string;
  version: number;
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

export const orgApi = {
  listLegalEntities: () => api.get<LegalEntity[]>("/v1/org/legal-entities"),
  createLegalEntity: (body: { name: string; short_name?: string; country_code?: string }) =>
    api.post<LegalEntity>("/v1/org/legal-entities", body),

  listLocations: () => api.get<Location[]>("/v1/org/locations"),
  createLocation: (body: {
    name: string; type: string; legal_entity_id?: string; city?: string;
    state_code?: string; country_code?: string; timezone?: string;
  }) => api.post<Location>("/v1/org/locations", body),

  listOrgUnits: () => api.get<OrgUnit[]>("/v1/org/org-units"),
  createOrgUnit: (body: {
    name: string; type: string; code?: string; parent_id?: string;
    legal_entity_id?: string; location_id?: string; effective_from: string;
  }) => api.post<OrgUnit>("/v1/org/org-units", body),

  listJobs: () => api.get<Job[]>("/v1/org/jobs"),
  createJob: (body: { title: string; code?: string; function?: string }) =>
    api.post<Job>("/v1/org/jobs", body),
};

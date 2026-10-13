import { api } from "./client";

export interface Employment {
  id: string;
  person_id: string;
  legal_entity_id: string;
  employee_number: string;
  first_name?: string | null;
  last_name?: string | null;
  full_name?: string | null;
  email?: string | null;
  role?: string | null;
  hire_date: string;
  separation_date: string | null;
  employment_state: string;
  service_stage: string | null;
  version: number;
  date_of_birth: string | null;
  gender: string | null;
  // Populated from the employee's current (open) assignment — null until a
  // HIRE personnel action has actually placed them (see personnelActionsApi).
  legal_entity_name: string | null;
  org_unit_id: string | null;
  department: string | null;
  team_name?: string | null;
  job_id: string | null;
  designation: string | null;
  grade_id?: string | null;
  grade?: string | null;
  position_id?: string | null;
  position_title?: string | null;
  location_id: string | null;
  location: string | null;
  manager_employment_id: string | null;
  manager_name: string | null;
}

export interface Person {
  id: string;
  legal_first_name: string;
  legal_last_name: string;
  preferred_name: string | null;
  date_of_birth: string | null;
  gender: string | null;
  version: number;
}

export interface MyProfile {
  id: string;
  legal_first_name: string;
  legal_last_name: string;
  preferred_name: string | null;
  date_of_birth: string | null;
  gender: string | null;
  nationality: string | null;
  email: string | null;
  mobile: string | null;
  version: number;
}

export type PersonnelActionType =
  | "HIRE" | "REHIRE" | "TRANSFER" | "PROMOTION" | "DEMOTION" | "CONFIRM"
  | "EXTEND_PROBATION" | "PLACE_ON_NOTICE" | "SEPARATION" | "CHANGE_MANAGER"
  | "CHANGE_GRADE" | "CHANGE_COST_CENTRE" | "CHANGE_JOB";

export interface PersonnelActionChanges {
  org_unit_id?: string;
  location_id?: string;
  job_id?: string;
  grade_id?: string;
  position_id?: string;
  cost_centre_id?: string;
  manager_employment_id?: string;
  /** Informational dates recorded with status actions (not placements). */
  probation_extended_until?: string;
  expected_last_working_day?: string;
  last_working_day?: string;
  note?: string;
}

export interface PersonnelAction {
  id: string;
  employment_id: string;
  type: PersonnelActionType;
  reason_code: string | null;
  effective_date: string;
  status: string;
  changes: PersonnelActionChanges | null;
  version: number;
}

export interface PersonnelActionListItem {
  id: string;
  type: PersonnelActionType;
  effective_date: string;
  status: string;
  submitted_at: string | null;
  failure_reason?: string | null;
  reason_code?: string | null;
  changes?: PersonnelActionChanges | null;
}

// The list endpoints cap a single response at 200 rows. A group with more people
// than that (a large tenant, or several companies together) would otherwise be
// silently truncated, so walk the pages until one comes back short.
const PAGE = 200;
async function fetchAll<T>(page: (offset: number) => Promise<T[]>): Promise<T[]> {
  const all: T[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const rows = await page(offset);
    all.push(...rows);
    if (rows.length < PAGE) return all;
  }
}

export const peopleApi = {
  listEmployees: (status?: string, limit = 50, offset = 0) => {
    const q = status ? `?filter[status]=${status}&limit=${limit}&offset=${offset}` : `?limit=${limit}&offset=${offset}`;
    return api.get<Employment[]>(`/v1/employees${q}`);
  },
  listAllEmployees: () => fetchAll((offset) => peopleApi.listEmployees(undefined, PAGE, offset)),
  getEmployee: (id: string) => api.get<Employment>(`/v1/employees/${id}`),
  listPersons: (limit = 200, offset = 0) => api.get<Person[]>(`/v1/persons?limit=${limit}&offset=${offset}`),
  listAllPersons: () => fetchAll((offset) => peopleApi.listPersons(PAGE, offset)),
  createPerson: (body: {
    legal_first_name: string;
    legal_last_name: string;
    preferred_name?: string;
    date_of_birth?: string | null;
    gender?: string | null;
  }) =>
    api.post<Person>("/v1/persons", body),
  createEmployment: (body: { person_id: string; legal_entity_id: string; employee_number?: string; hire_date: string }) =>
    api.post<Employment>("/v1/employees", body),
  getMyProfile: () => api.get<MyProfile>("/v1/persons/me"),
  updateMyProfile: (body: {
    preferred_name?: string | null;
    date_of_birth?: string | null;
    gender?: string | null;
    nationality?: string | null;
    mobile?: string | null;
  }) => api.patch<MyProfile>("/v1/persons/me", body),
};

export const personnelActionsApi = {
  create: (body: {
    employment_id: string;
    type: PersonnelActionType;
    effective_date: string;
    reason_code?: string;
    changes?: PersonnelActionChanges;
    /** Why HR is changing a field a connected app (e.g. the ERP) owns for this employee. */
    override_reason?: string;
  }) => api.post<PersonnelAction>("/v1/personnel-actions", body),
  list: (employmentId: string) =>
    api.get<PersonnelActionListItem[]>(`/v1/personnel-actions?employment_id=${employmentId}`),
  cancel: (actionId: string) => api.post<PersonnelAction>(`/v1/personnel-actions/${actionId}/cancel`, {}),
};

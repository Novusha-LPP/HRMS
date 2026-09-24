import { api } from "./client";

export interface Employment {
  id: string;
  person_id: string;
  legal_entity_id: string;
  employee_number: string;
  hire_date: string;
  separation_date: string | null;
  employment_state: string;
  service_stage: string | null;
  version: number;
  // Populated from the employee's current (open) assignment — null until a
  // HIRE personnel action has actually placed them (see personnelActionsApi).
  legal_entity_name: string | null;
  org_unit_id: string | null;
  department: string | null;
  job_id: string | null;
  designation: string | null;
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
  | "CHANGE_GRADE" | "CHANGE_COST_CENTRE";

export interface PersonnelActionChanges {
  org_unit_id?: string;
  location_id?: string;
  job_id?: string;
  grade_id?: string;
  position_id?: string;
  cost_centre_id?: string;
  manager_employment_id?: string;
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
}

export const peopleApi = {
  listEmployees: (status?: string, limit = 50) => {
    const q = status ? `?filter[status]=${status}&limit=${limit}` : `?limit=${limit}`;
    return api.get<Employment[]>(`/v1/employees${q}`);
  },
  getEmployee: (id: string) => api.get<Employment>(`/v1/employees/${id}`),
  listPersons: (limit = 200) => api.get<Person[]>(`/v1/persons?limit=${limit}`),
  createPerson: (body: { legal_first_name: string; legal_last_name: string; preferred_name?: string }) =>
    api.post<Person>("/v1/persons", body),
  createEmployment: (body: { person_id: string; legal_entity_id: string; employee_number: string; hire_date: string }) =>
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
  }) => api.post<PersonnelAction>("/v1/personnel-actions", body),
  list: (employmentId: string) =>
    api.get<PersonnelActionListItem[]>(`/v1/personnel-actions?employment_id=${employmentId}`),
};

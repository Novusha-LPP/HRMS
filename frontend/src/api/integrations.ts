import { api } from "./client";

/** Settings → Integrations (backend: modules/integrations/admin.py). */

export type AppKind = "TWO_WAY" | "RECEIVE_ONLY" | "READ_ONLY";
export type AppStatus = "ACTIVE" | "PAUSED" | "DISCONNECTED";
export type Owner = "APP" | "HRMS" | "SHARED" | "NOT_SYNCED";
export type Lifecycle = "APP" | "HRMS" | "BOTH";
export type DataClass = "BASIC" | "CONTACT" | "PERSONAL" | "ATTENDANCE_LEAVE";

export interface ConnectedApp {
  id: string;
  code: string;
  name: string;
  kind: AppKind;
  status: AppStatus;
  created_at: string;
  linked_employees: number;
  active_keys: number;
  last_request_at: string | null;
  feed_position: string | null;
  feed_read_at: string | null;
  feed_lag: number;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  client_id: string;
  environment: "test" | "live";
  scopes: string[];
  allowed_ips: string[] | null;
  legal_entity_ids: string[] | null;
  status: "ACTIVE" | "EXPIRED" | "REVOKED";
  expires_at: string | null;
  created_at: string;
  last_used_at: string | null;
  last_used_ip: string | null;
  /** Calls in the last hour (from the key's rate-limit counters). */
  calls_last_hour: number;
  rate_limit_per_minute: number;
  revoked_at: string | null;
  revoke_reason: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  /** Shown once. */
  key: string;
}

export interface KeyInput {
  name: string;
  scopes: string[];
  allowed_ips?: string[] | null;
  legal_entity_ids?: string[] | null;
  expires_in_days?: number | null;
  rate_limit_per_minute?: number;
}

export interface IntegrationSettings {
  field_ownership: Record<string, Owner>;
  inbound_unowned: "IGNORE" | "REJECT";
  hr_override: "NOT_ALLOWED" | "WITH_REASON" | "WITH_APPROVAL";
  lifecycle: { hire: Lifecycle; job_change: Lifecycle; exit: Lifecycle; rehire: Lifecycle };
  unknown_values: "REJECT" | "CREATE";
  matching: "CODE_NAME_DOB" | "CODE_EMAIL" | "NEVER";
  logins: {
    password_source: "APP_THEN_DEFAULT" | "DEFAULT" | "NONE";
    default_pattern: string;
    force_change: boolean;
  };
  self_service: {
    punch: boolean;
    attendance: boolean;
    corrections: boolean;
    leave: boolean;
    profile_edit: boolean;
    approvals: boolean;
    marking: boolean;
    session_minutes: number;
  };
  safety: { max_exits_per_day: number; max_exit_percent: number; over_limit: "HOLD" | "REJECT" };
  outbound: {
    events: string[];
    data_classes: DataClass[];
    fields: string[] | null;
    legal_entity_ids: string[] | null;
    org_unit_ids: string[] | null;
    timing: { mode: "ON_SAVE" | "DAYS_BEFORE_JOIN" | "ON_JOIN"; days: number };
  };
  default_location_id: string | null;
  retention_days: number;
}

export interface CatalogField {
  field: string;
  label: string;
  data_class: DataClass;
  ownable: boolean;
}

export interface Catalog {
  fields: CatalogField[];
  presets: { id: string; label: string; description: string; field_ownership: Record<string, Owner> }[];
  scopes: { scope: string; description: string }[];
  events: string[];
  data_classes: DataClass[];
  defaults: Record<AppKind, IntegrationSettings>;
  key_environment: "test" | "live";
}

export interface EffectiveSettings {
  app_id: string;
  legal_entity_id: string | null;
  settings: IntegrationSettings;
  overridden: string[];
  warnings: string[];
}

export interface Profile {
  id: string;
  app_id: string;
  legal_entity_id: string | null;
  version: number;
  status: "DRAFT" | "PUBLISHED" | "SUPERSEDED" | "DISCARDED";
  effective_from: string | null;
  settings: Partial<IntegrationSettings>;
  note: string | null;
  created_at: string;
  published_at: string | null;
}

export interface Preview {
  linked_employees_affected: number;
  fields_becoming_locked: string[];
  fields_becoming_unlocked: string[];
  employees_with_recent_hr_edits_to_newly_locked_fields: number;
  events_switched_on: string[];
  events_switched_off: string[];
  lifecycle: Record<string, { from: Lifecycle; to: Lifecycle }>;
  warnings: string[];
}

export type MappingKind = "LEGAL_ENTITY" | "DEPARTMENT" | "LOCATION" | "DESIGNATION" | "ROLE";

export interface Mapping {
  id: string;
  kind: MappingKind;
  external_value: string;
  target_id: string | null;
  target_value: string | null;
  target_name: string | null;
  created_at: string;
}

export interface UnmappedValue {
  kind: MappingKind;
  value: string;
  requests: number;
  last_seen: string;
}

export interface SyncLogEntry {
  id: string;
  operation: string;
  external_id: string | null;
  employment_id: string | null;
  employee_name: string | null;
  outcome: string;
  error_code: string | null;
  error_detail: Record<string, unknown> | null;
  changes: Record<string, { old: unknown; new: unknown }> | null;
  warnings: string[] | null;
  http_status: number | null;
  duration_ms: number | null;
  request_id: string | null;
  created_at: string;
  key_prefix: string | null;
}

export interface Duplicate {
  id: string;
  external_id: string;
  match_reason: string;
  created_at: string;
  app_record: Record<string, unknown> | null;
  hrms_employee: {
    employment_id: string;
    employee_code: string;
    first_name: string;
    last_name: string;
    date_of_birth: string | null;
    email: string | null;
  };
}

export interface HeldExit {
  id: string;
  external_id: string;
  employment_id: string;
  employee_name: string;
  employee_code: string;
  last_working_day: string | null;
  requested_at: string;
}

export interface NotLinked {
  employment_id: string;
  employee_code: string;
  employee_name: string;
  hire_date: string;
  announced_at: string;
}

export interface AppReport {
  app: { code: string; name: string; kind: AppKind; status: AppStatus };
  events: string[];
  data_classes: DataClass[];
  fields: string[];
  people: { companies: string[] | string; departments: string[] | string };
  scopes_granted: string[];
  keys: { name: string; prefix: string; status: string; last_used_at: string | null }[];
  last_feed_read_at: string | null;
  employees_delivered_through_feed: number;
  linked_employees: number;
  never_sent: string;
}

export interface FieldControl {
  field: string;
  label: string;
  owner: string;
  owner_name: string | null;
  locked: boolean;
  override: "NOT_ALLOWED" | "WITH_REASON" | "WITH_APPROVAL" | null;
  external_ids: Record<string, string>;
}

const B = "/v1/admin/integrations";
const q = (params: Record<string, string | null | undefined>) => {
  const s = Object.entries(params)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`)
    .join("&");
  return s ? `?${s}` : "";
};

export const integrationsApi = {
  catalog: () => api.get<Catalog>(`${B}/catalog`),
  apps: () => api.get<ConnectedApp[]>(`${B}/apps`),
  createApp: (body: { code: string; name: string; kind: AppKind }) => api.post<ConnectedApp>(`${B}/apps`, body),
  updateApp: (id: string, body: { name?: string; status?: AppStatus }) => api.patch<ConnectedApp>(`${B}/apps/${id}`, body),

  keys: (appId: string) => api.get<ApiKey[]>(`${B}/apps/${appId}/keys`),
  createKey: (appId: string, body: KeyInput) => api.post<ApiKeyCreated>(`${B}/apps/${appId}/keys`, body),
  revokeKey: (appId: string, keyId: string, reason: string) =>
    api.post<ApiKey>(`${B}/apps/${appId}/keys/${keyId}/revoke`, { reason }),

  settings: (appId: string, legalEntityId?: string | null) =>
    api.get<EffectiveSettings>(`${B}/apps/${appId}/settings${q({ legal_entity_id: legalEntityId })}`),
  profiles: (appId: string, legalEntityId?: string | null) =>
    api.get<Profile[]>(`${B}/apps/${appId}/profiles${q({ legal_entity_id: legalEntityId })}`),
  createProfile: (appId: string, body: { legal_entity_id?: string | null; preset?: string; settings?: Partial<IntegrationSettings>; note?: string }) =>
    api.post<Profile>(`${B}/apps/${appId}/profiles`, body),
  updateProfile: (profileId: string, settings: Partial<IntegrationSettings>, note?: string) =>
    api.put<Profile>(`${B}/profiles/${profileId}`, { settings, note }),
  discardProfile: (profileId: string) => api.post<Profile>(`${B}/profiles/${profileId}/discard`, {}),
  previewProfile: (profileId: string) => api.post<Preview>(`${B}/profiles/${profileId}/preview`, {}),
  publishProfile: (profileId: string, effectiveFrom: string) =>
    api.post<Profile>(`${B}/profiles/${profileId}/publish`, { effective_from: effectiveFrom }),

  mappings: (appId: string) => api.get<Mapping[]>(`${B}/apps/${appId}/mappings`),
  createMapping: (appId: string, body: { kind: MappingKind; external_value: string; target_id?: string; target_value?: "EMPLOYEE" | "MANAGER" }) =>
    api.post<Mapping>(`${B}/apps/${appId}/mappings`, body),
  deleteMapping: (appId: string, mappingId: string) => api.delete(`${B}/apps/${appId}/mappings/${mappingId}`),
  unmapped: (appId: string) => api.get<UnmappedValue[]>(`${B}/apps/${appId}/unmapped`),

  log: (appId: string, filters: { outcome?: string; operation?: string; external_id?: string; before?: string }) =>
    api.get<SyncLogEntry[]>(`${B}/apps/${appId}/requests${q(filters)}`),
  duplicates: (appId: string) => api.get<Duplicate[]>(`${B}/apps/${appId}/duplicates`),
  resolveDuplicate: (id: string, decision: "SAME_PERSON" | "DIFFERENT_PERSON") =>
    api.post<{ status: string }>(`${B}/duplicates/${id}/resolve`, { decision }),
  heldExits: (appId: string) => api.get<HeldExit[]>(`${B}/apps/${appId}/held-exits`),
  decideHeldExit: (id: string, decision: "RELEASE" | "REJECT") =>
    api.post<{ decision: string; outcome: string }>(`${B}/held-exits/${id}`, { decision }),
  notLinked: (appId: string) => api.get<NotLinked[]>(`${B}/apps/${appId}/not-linked`),
  report: (appId: string) => api.get<AppReport>(`${B}/apps/${appId}/report`),

  fieldControl: (employmentId: string) => api.get<FieldControl[]>(`/v1/employees/${employmentId}/field-control`),
};

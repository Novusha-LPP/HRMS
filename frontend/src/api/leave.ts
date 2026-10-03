import { api } from "./client";

export interface LeaveType {
  id: string;
  name: string;
  code: string;
  days_per_year: number;
  carry_forward: boolean;
  max_carry_forward_days: number | null;
  requires_approval: boolean;
  approval_levels: number;
  cancel_requires_approval: boolean;
  cancel_approval_levels: number;
  min_days_per_application: number;
  max_days_per_application: number | null;
  advance_notice_days: number;
  requires_document: boolean;
  is_paid: boolean;
  is_active: boolean;
  color: string;
  is_comp_off: boolean;
  encashable: boolean;
  accrual_enabled: boolean;
}

export interface Holiday {
  id: string;
  holiday_date: string;
  name: string;
  legal_entity_id: string | null;
  is_optional: boolean;
}

export interface CompOffGrant {
  id: string;
  employment_id: string;
  work_date: string;
  days_granted: number;
  notes: string | null;
  granted_by: string | null;
  recorded_at: string;
}

export interface LeaveEncashment {
  id: string;
  employment_id: string;
  leave_type_id: string;
  leave_type_name: string;
  days: number;
  effective_date: string;
  notes: string | null;
  processed_by: string | null;
  recorded_at: string;
}

export interface LeaveBalanceAdjustment {
  employment_id: string;
  leave_type_id: string;
  leave_type_name: string;
  kind: string;
  quantity: number;
  new_balance: number;
  effective_date: string;
  reason: string;
}

export interface AccrualRunResult {
  period: string;
  balances_credited: number;
  days_credited_total: number;
}

export interface YearEndCloseResult {
  fy_year: number;
  buckets_closed: number;
  days_lapsed: number;
}

export interface LeaveBalance {
  id: string;
  employment_id: string;
  leave_type_id: string;
  leave_type_name: string;
  leave_type_code: string;
  year: number;
  allocated_days: number;
  carry_forward_days: number;
  used_days: number;
  pending_days: number;
  available_days: number;
  color: string;
}

export interface LeaveApprovalAction {
  id: string;
  application_id: string;
  action_type: string;
  level: number;
  approver_employment_id: string | null;
  comments: string | null;
  actioned_at: string;
}

export interface LeaveApplication {
  id: string;
  employment_id: string;
  leave_type_id: string;
  leave_type_name: string;
  leave_type_code: string;
  leave_type_color: string;
  from_date: string;
  to_date: string;
  days_requested: number;
  half_day_option: string;
  reason: string | null;
  status: string;
  current_level: number;
  total_levels: number;
  applied_at: string | null;
  cancel_reason: string | null;
  cancel_requested_at: string | null;
  approval_history: LeaveApprovalAction[];
}

/** Statuses that wait on an approver's decision (leave or its cancellation). */
export const DECISION_STATUSES = [
  "PENDING_L1", "PENDING_L2", "PENDING_L3", "PENDING",
  "CANCEL_PENDING_L1", "CANCEL_PENDING_L2", "CANCEL_PENDING_L3", "CANCEL_PENDING",
];

/** Page size for the applications list; a shorter page is the last one. */
export const LEAVE_PAGE_SIZE = 100;

export interface LeaveApplicationSummary {
  by_status: Record<string, number>;
  approved_days_by_type: { leave_type_id: string; name: string; color: string; days: number }[];
}

export const leaveApi = {
  listTypes: () => api.get<LeaveType[]>("/v1/leave/types"),
  createType: (body: Partial<LeaveType>) => api.post<LeaveType>("/v1/leave/types", body),
  updateType: (id: string, body: Partial<LeaveType>) => api.patch<LeaveType>(`/v1/leave/types/${id}`, body),

  /** year is a financial-year label (e.g. 2026 for FY2026-27), not a calendar year. */
  getBalances: (employmentId: string, year?: number) => {
    const q = year ? `?employment_id=${employmentId}&year=${year}` : `?employment_id=${employmentId}`;
    return api.get<LeaveBalance[]>(`/v1/leave/balances${q}`);
  },

  /** Newest first, one page. `statuses` are OR-ed; `after` is the last id of the previous page. */
  listApplications: (opts: { employmentId?: string; statuses?: string[]; limit?: number; after?: string } = {}) => {
    const params = new URLSearchParams();
    if (opts.employmentId) params.set("employment_id", opts.employmentId);
    if (opts.statuses?.length) params.set("status", opts.statuses.join(","));
    params.set("limit", String(opts.limit ?? LEAVE_PAGE_SIZE));
    if (opts.after) params.set("after", opts.after);
    return api.get<LeaveApplication[]>(`/v1/leave/applications?${params}`);
  },
  /** Counts by status and approved days by type for everyone in the caller's scope. */
  applicationSummary: (legalEntityId?: string) =>
    api.get<LeaveApplicationSummary>(
      `/v1/leave/applications/summary${legalEntityId ? `?legal_entity_id=${encodeURIComponent(legalEntityId)}` : ""}`,
    ),
  createApplication: (employmentId: string, body: {
    leave_type_id: string;
    from_date: string;
    to_date: string;
    half_day_option?: string;
    document_id?: string;
    reason?: string;
  }) => api.post<LeaveApplication>(`/v1/leave/applications?employment_id=${employmentId}`, body),

  submit: (appId: string, employmentId: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/submit?employment_id=${employmentId}`, {}),

  // The approver is always the signed-in account (from the token) — no id is passed.
  approve: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/approve`, { action: "APPROVE", comments }),

  reject: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/reject`, { action: "REJECT", comments }),

  cancel: (appId: string, employmentId: string, cancelReason?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/cancel?employment_id=${employmentId}`, { cancel_reason: cancelReason }),

  cancelApprove: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/cancel-approve`, { action: "APPROVE", comments }),

  cancelReject: (appId: string, comments?: string) =>
    api.post<LeaveApplication>(`/v1/leave/applications/${appId}/cancel-reject`, { action: "REJECT", comments }),

  listHolidays: (year?: number) => api.get<Holiday[]>(`/v1/time/holidays${year ? `?year=${year}` : ""}`),
  createHoliday: (body: { holiday_date: string; name: string; is_optional?: boolean }) =>
    api.post<Holiday>("/v1/time/holidays", body),
  deleteHoliday: (id: string) => api.delete(`/v1/time/holidays/${id}`),

  grantCompOff: (body: { employment_id: string; work_date: string; days_granted?: number; notes?: string }) =>
    api.post<CompOffGrant>("/v1/leave/comp-off", body),

  encash: (body: { employment_id: string; leave_type_id: string; days: number; notes?: string }) =>
    api.post<LeaveEncashment>("/v1/leave/encashment", body),

  adjustBalance: (body: {
    employment_id: string;
    leave_type_id: string;
    quantity: number;
    effective_date?: string;
    reason: string;
    kind: "OPENING" | "ADJUSTMENT";
  }) => api.post<LeaveBalanceAdjustment>("/v1/leave/balances/adjust", body),

  runAccrual: (period?: string) =>
    api.post<AccrualRunResult>(`/v1/leave/accrual/run${period ? `?period=${period}` : ""}`, {}),

  /** fyYear is a label (e.g. 2026 for FY2026-27) — caps each bucket's closing balance at its
   * policy's carry-forward cap (lapsing the rest); uncapped buckets just carry everything forward. */
  yearEndClose: (fyYear: number) =>
    api.post<YearEndCloseResult>(`/v1/leave/year-end-close?fy_year=${fyYear}`, {}),

  // ─── Buckets & Mappings ──────────────────────────────────────────────────
  // Internal ledger plumbing only, no longer surfaced as a management UI:
  // Policy Sets resolves/creates these behind the scenes per leave type, and
  // the ledger view lists them to label a monthly balance row.
  listBuckets: () => api.get<LeaveBalanceBucket[]>("/v1/leave/buckets"),
  createBucket: (body: { name: string; code: string; is_unlimited?: boolean }) =>
    api.post<LeaveBalanceBucket>("/v1/leave/buckets", body),

  listBucketMappings: () => api.get<LeaveTypeBucketMapping[]>("/v1/leave/bucket-mappings"),
  createBucketMapping: (body: { leave_type_id: string; bucket_id: string }) =>
    api.post<LeaveTypeBucketMapping>("/v1/leave/bucket-mappings", body),

  // ─── Policy Sets & Bucket Policies ───────────────────────────────────────
  listPolicySets: () => api.get<LeavePolicySet[]>("/v1/leave/policy-sets"),
  createPolicySet: (body: { name: string; description?: string; is_default?: boolean }) =>
    api.post<LeavePolicySet>("/v1/leave/policy-sets", body),
  updatePolicySet: (id: string, body: { name?: string; description?: string; is_default?: boolean }) =>
    api.patch<LeavePolicySet>(`/v1/leave/policy-sets/${id}`, body),

  listBucketPolicies: (setId: string) =>
    api.get<LeaveBucketPolicy[]>(`/v1/leave/policy-sets/${setId}/bucket-policies`),
  createBucketPolicy: (setId: string, body: {
    bucket_id: string;
    accrual_type: "ANNUAL_UPFRONT" | "MONTHLY_PRORATE" | "NONE";
    days_per_year: number;
    carry_forward_enabled?: boolean;
    max_carry_forward_days?: number | null;
    lapse_enabled?: boolean;
    encashment_enabled?: boolean;
    max_encashment_days?: number | null;
    probation_eligible?: boolean;
    min_service_months?: number;
    pro_rate_first_year?: boolean;
  }) => api.post<LeaveBucketPolicy>(`/v1/leave/policy-sets/${setId}/bucket-policies`, body),
  updateBucketPolicy: (id: string, body: Partial<{
    accrual_type: "ANNUAL_UPFRONT" | "MONTHLY_PRORATE" | "NONE";
    days_per_year: number;
    carry_forward_enabled: boolean;
    max_carry_forward_days: number | null;
    lapse_enabled: boolean;
    encashment_enabled: boolean;
    max_encashment_days: number | null;
    probation_eligible: boolean;
    min_service_months: number;
    pro_rate_first_year: boolean;
  }>) => api.patch<LeaveBucketPolicy>(`/v1/leave/bucket-policies/${id}`, body),
  deleteBucketPolicy: (id: string) => api.delete(`/v1/leave/bucket-policies/${id}`),

  // ─── Policy Assignments ──────────────────────────────────────────────────
  listPolicyAssignments: () => api.get<LeavePolicyAssignment[]>("/v1/leave/policy-assignments"),
  createPolicyAssignment: (body: {
    leave_policy_set_id: string;
    effective_from: string;
    effective_to?: string;
    employment_id?: string;
    org_unit_id?: string;
    legal_entity_id?: string;
  }) => api.post<LeavePolicyAssignment>("/v1/leave/policy-assignments", body),
  deletePolicyAssignment: (id: string) => api.delete(`/v1/leave/policy-assignments/${id}`),

  // ─── Monthly Ledger & Transaction History ────────────────────────────────
  getLedger: (employmentId: string, params?: { bucket_id?: string; fy_year?: number; calendar_year?: number }) => {
    const q = new URLSearchParams({ employment_id: employmentId });
    if (params?.bucket_id) q.set("bucket_id", params.bucket_id);
    if (params?.fy_year) q.set("fy_year", String(params.fy_year));
    if (params?.calendar_year) q.set("calendar_year", String(params.calendar_year));
    return api.get<LeaveMonthlyLedger[]>(`/v1/leave/ledger?${q}`);
  },

  getTransactions: (employmentId: string, params?: { bucket_id?: string; from_date?: string; to_date?: string }) => {
    const q = new URLSearchParams({ employment_id: employmentId });
    if (params?.bucket_id) q.set("bucket_id", params.bucket_id);
    if (params?.from_date) q.set("from_date", params.from_date);
    if (params?.to_date) q.set("to_date", params.to_date);
    return api.get<LeaveBalanceTransaction[]>(`/v1/leave/transactions?${q}`);
  },
};

// ─── Phase 2 Config & Ledger Interfaces ─────────────────────────────────────

export interface LeaveBalanceBucket {
  id: string;
  name: string;
  code: string;
  is_unlimited: boolean;
  is_active: boolean;
}

export interface LeaveTypeBucketMapping {
  id: string;
  leave_type_id: string;
  leave_type_name: string;
  leave_type_code: string;
  bucket_id: string;
  bucket_name: string;
  bucket_code: string;
}

export interface LeavePolicySet {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
}

export interface LeaveBucketPolicy {
  id: string;
  policy_set_id: string;
  bucket_id: string;
  bucket_name: string;
  bucket_code: string;
  accrual_type: "ANNUAL_UPFRONT" | "MONTHLY_PRORATE" | "NONE";
  days_per_year: number;
  carry_forward_enabled: boolean;
  max_carry_forward_days: number | null;
  lapse_enabled: boolean;
  encashment_enabled: boolean;
  max_encashment_days: number | null;
  probation_eligible: boolean;
  min_service_months: number;
  pro_rate_first_year: boolean;
}

export interface LeavePolicyAssignment {
  id: string;
  leave_policy_set_id: string;
  leave_policy_set_name: string;
  effective_from: string;
  effective_to: string | null;
  employment_id: string | null;
  org_unit_id: string | null;
  legal_entity_id: string | null;
}

export interface LeaveMonthlyLedger {
  id: string;
  employment_id: string;
  bucket_id: string;
  bucket_name: string;
  bucket_code: string;
  calendar_year: number;
  calendar_month: number;
  fy_year: number;
  opening: number;
  accrued: number;
  granted: number;
  held: number;
  adjustment: number;
  taken: number;
  lapsed: number;
  encashed: number;
  closing: number;
  available: number;
}

export interface LeaveBalanceTransaction {
  id: string;
  employment_id: string;
  bucket_id: string;
  bucket_name: string;
  bucket_code: string;
  leave_type_id: string | null;
  leave_type_name: string | null;
  leave_type_code: string | null;
  transaction_type: string;
  quantity: number;
  previous_balance: number;
  new_balance: number;
  effective_date: string;
  reason: string | null;
  reference_id: string | null;
  reference_type: string | null;
  recorded_by: string;
  approved_by: string | null;
  recorded_at: string;
}


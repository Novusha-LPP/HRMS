import { api, API_BASE_URL } from "./client";

export type OpeningStatus = "DRAFT" | "PENDING_APPROVAL" | "REJECTED" | "OPEN" | "ON_HOLD" | "FILLED" | "CLOSED";
export type EmploymentType = "FULL_TIME" | "PART_TIME" | "CONTRACT" | "INTERN" | "CONSULTANT";
export type WorkMode = "ONSITE" | "HYBRID" | "REMOTE";
export type Priority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type OpeningReason = "NEW_ROLE" | "REPLACEMENT" | "EXPANSION";
export type StageCategory = "ACTIVE" | "HIRED" | "REJECTED" | "WITHDRAWN";
export type StageColor = "neutral" | "brand" | "info" | "plum" | "warning" | "success" | "danger";
export type LinkType = "LINKEDIN" | "GITHUB" | "PORTFOLIO" | "WEBSITE" | "OTHER";
export type CandidateSource = "REFERRAL" | "LINKEDIN" | "JOB_PORTAL" | "CAREERS_SITE" | "AGENCY" | "CAMPUS" | "WALK_IN" | "OTHER";

export interface LookupItem { id: string; name: string; legal_entity_id: string | null; detail: string | null }

export interface RecruitmentAccess {
  can_request: boolean;
  can_manage: boolean;
  can_approve: boolean;
  departments: LookupItem[];
  jobs: LookupItem[];
  locations: LookupItem[];
  hiring_managers: LookupItem[];
}

export interface Stage {
  id: string;
  name: string;
  category: StageCategory;
  color: StageColor;
  sequence: number;
  is_active: boolean;
  version: number;
}

export interface OpeningSummary {
  id: string;
  code: string;
  title: string;
  status: OpeningStatus;
  priority: Priority;
  employment_type: EmploymentType;
  work_mode: WorkMode;
  positions: number;
  hired: number;
  candidates: number;
  in_progress: number;
  legal_entity_id: string;
  legal_entity_name: string | null;
  org_unit_id: string;
  org_unit_name: string | null;
  job_title: string | null;
  location_name: string | null;
  hiring_manager_employment_id: string | null;
  hiring_manager_name: string | null;
  requested_by_name: string | null;
  target_start_date: string | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  stage_counts: { stage_id: string; count: number }[];
}

export interface OpeningDetail extends OpeningSummary {
  job_id: string | null;
  location_id: string | null;
  reason: OpeningReason;
  replacement_for: string | null;
  min_experience_years: string | null;
  max_experience_years: string | null;
  salary_min: string | null;
  salary_max: string | null;
  currency: string;
  description: string;
  responsibilities: string | null;
  requirements: string | null;
  skills: string[];
  approval_mode: "FLOW" | "HR" | "AUTO" | null;
  approval_instance_id: string | null;
  approved_at: string | null;
  approved_by_name: string | null;
  decision_comment: string | null;
  closed_at: string | null;
  close_reason: string | null;
  version: number;
  can_edit: boolean;
  can_submit: boolean;
  can_withdraw: boolean;
  can_decide: boolean;
  can_manage: boolean;
}

export interface OpeningInput {
  title: string;
  org_unit_id: string;
  job_id: string | null;
  location_id: string | null;
  hiring_manager_employment_id: string | null;
  employment_type: EmploymentType;
  work_mode: WorkMode;
  positions: number;
  priority: Priority;
  reason: OpeningReason;
  replacement_for: string | null;
  min_experience_years: number | null;
  max_experience_years: number | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string;
  target_start_date: string | null;
  description: string;
  responsibilities: string | null;
  requirements: string | null;
  skills: string[];
}

export interface CandidateLink { type: LinkType; label?: string | null; url: string }

export interface Candidate {
  id: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  current_company: string | null;
  current_title: string | null;
  total_experience_years: string | null;
  current_ctc: string | null;
  expected_ctc: string | null;
  notice_period_days: number | null;
  source: CandidateSource;
  source_detail: string | null;
  links: CandidateLink[];
  skills: string[];
  summary: string | null;
  resume: { file_name: string; mime_type: string; size: number; uploaded_at: string } | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface CandidateInput {
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  current_company: string | null;
  current_title: string | null;
  total_experience_years: number | null;
  current_ctc: number | null;
  expected_ctc: number | null;
  notice_period_days: number | null;
  source: CandidateSource;
  source_detail: string | null;
  links: CandidateLink[];
  skills: string[];
  summary: string | null;
}

export interface Application {
  id: string;
  opening_id: string;
  opening_code: string;
  opening_title: string;
  opening_status: OpeningStatus;
  candidate: Candidate;
  stage_id: string;
  stage_name: string;
  stage_category: StageCategory;
  rating: number | null;
  hired_employment_id: string | null;
  outcome_reason: string | null;
  applied_at: string;
  stage_changed_at: string;
  notes_count: number;
  version: number;
  matched_existing?: boolean;
}

export interface RecruitmentEvent {
  id: string;
  action: string;
  actor_name: string | null;
  application_id: string | null;
  candidate_name: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ApplicationRef {
  id: string;
  opening_id: string;
  opening_code: string;
  opening_title: string;
  stage_name: string;
  stage_category: StageCategory | "";
  stage_color?: StageColor;
}

export interface ApplicationDetail extends Application {
  events: RecruitmentEvent[];
  other_applications: ApplicationRef[];
  can_manage: boolean;
  can_hire: boolean;
  hire_defaults: {
    first_name: string;
    last_name: string;
    legal_entity_id: string;
    org_unit_id: string;
    job_id: string | null;
    location_id: string | null;
    manager_employment_id: string | null;
    hire_date: string | null;
  } | null;
}

export interface CandidatePage {
  total: number;
  items: { candidate: Candidate; applications: ApplicationRef[] }[];
}

const base = "/v1/recruitment";

export const recruitmentApi = {
  access: () => api.get<RecruitmentAccess>(`${base}/access`),
  stages: () => api.get<Stage[]>(`${base}/stages`),
  saveStages: (stages: { id?: string; name: string; category: StageCategory; color: StageColor; is_active: boolean }[]) =>
    api.put<Stage[]>(`${base}/stages`, { stages }),

  openings: (params: { status?: string; q?: string; mine?: boolean } = {}) => {
    const p = new URLSearchParams();
    if (params.status) p.set("status", params.status);
    if (params.q) p.set("q", params.q);
    if (params.mine) p.set("mine", "true");
    const qs = p.toString();
    return api.get<OpeningSummary[]>(`${base}/openings${qs ? `?${qs}` : ""}`);
  },
  opening: (id: string) => api.get<OpeningDetail>(`${base}/openings/${id}`),
  createOpening: (body: OpeningInput, submit: boolean) =>
    api.post<OpeningDetail>(`${base}/openings${submit ? "?submit=true" : ""}`, body),
  updateOpening: (id: string, body: OpeningInput & { version: number }) =>
    api.put<OpeningDetail>(`${base}/openings/${id}`, body),
  deleteOpening: (id: string) => api.delete(`${base}/openings/${id}`),
  submitOpening: (id: string) => api.post<OpeningDetail>(`${base}/openings/${id}/submit`, {}),
  withdrawOpening: (id: string) => api.post<OpeningDetail>(`${base}/openings/${id}/withdraw`, {}),
  decideOpening: (id: string, action: "APPROVE" | "REJECT", comments: string) =>
    api.post<OpeningDetail>(`${base}/openings/${id}/decision`, { action, comments: comments || null }),
  setOpeningStatus: (id: string, status: "OPEN" | "ON_HOLD" | "CLOSED", reason: string) =>
    api.post<OpeningDetail>(`${base}/openings/${id}/status`, { status, reason: reason || null }),
  openingEvents: (id: string) => api.get<RecruitmentEvent[]>(`${base}/openings/${id}/events`),

  applications: (openingId: string) => api.get<Application[]>(`${base}/openings/${openingId}/applications`),
  addApplication: (openingId: string, body: { candidate_id?: string; candidate?: CandidateInput; stage_id?: string | null; note?: string | null }) =>
    api.post<Application>(`${base}/openings/${openingId}/applications`, body),
  application: (id: string) => api.get<ApplicationDetail>(`${base}/applications/${id}`),
  moveApplication: (id: string, stageId: string, reason: string | null, expectedVersion?: number) =>
    api.post<ApplicationDetail>(`${base}/applications/${id}/move`, { stage_id: stageId, reason, expected_version: expectedVersion }),
  rateApplication: (id: string, rating: number | null) =>
    api.patch<ApplicationDetail>(`${base}/applications/${id}`, rating === null ? { clear_rating: true } : { rating }),
  addNote: (id: string, body: string) => api.post<ApplicationDetail>(`${base}/applications/${id}/notes`, { body }),
  linkHire: (id: string, employmentId: string) =>
    api.post<ApplicationDetail>(`${base}/applications/${id}/hire`, { employment_id: employmentId }),

  candidates: (params: { q?: string; limit?: number; offset?: number } = {}) => {
    const p = new URLSearchParams();
    if (params.q) p.set("q", params.q);
    p.set("limit", String(params.limit ?? 50));
    p.set("offset", String(params.offset ?? 0));
    return api.get<CandidatePage>(`${base}/candidates?${p.toString()}`);
  },
  candidate: (id: string) => api.get<Candidate>(`${base}/candidates/${id}`),
  updateCandidate: (id: string, body: CandidateInput & { version: number }) =>
    api.put<Candidate>(`${base}/candidates/${id}`, body),
  deleteCandidate: (id: string) => api.delete(`${base}/candidates/${id}`),
  uploadResume: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.postForm<Candidate>(`${base}/candidates/${id}/resume`, fd);
  },
  deleteResume: (id: string) => api.delete<Candidate>(`${base}/candidates/${id}/resume`),

  /** Fetch the resume with the session (cookie) and hand back an object URL. */
  async fetchResume(candidateId: string, inline: boolean): Promise<{ blob: Blob; url: string }> {
    const res = await fetch(`${API_BASE_URL}${base}/candidates/${candidateId}/resume${inline ? "?inline=true" : ""}`, {
      headers: { "X-HRMS-Session": "cookie" }, credentials: "include", signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) throw new Error("Couldn’t load the resume");
    const blob = await res.blob();
    return { blob, url: URL.createObjectURL(blob) };
  },
};

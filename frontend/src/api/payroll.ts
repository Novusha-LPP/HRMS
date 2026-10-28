import { api } from "./client";

/** Amounts arrive as decimal strings (never floats) so paise are exact. */
export type Money = string;

export interface StatutoryRule {
  id: string;
  rule_code: string;
  label: string;
  unit: "PERCENT" | "AMOUNT" | "FLAG";
  state_code: string | null;
  value: string;
  effective_from: string;
  effective_to: string | null;
  source: string;
  verified: boolean;
  verified_by_name: string | null;
  verified_at: string | null;
  /** The person who entered it; they can't verify it themselves. */
  recorded_by_id: string | null;
  recorded_by_name: string | null;
  status: string;
}

export type ComponentKind = "EARNING" | "DEDUCTION" | "EMPLOYER_CONTRIBUTION" | "REIMBURSEMENT" | "INFO";
export type StatutoryCode = "PF_EMPLOYEE" | "PF_EMPLOYER" | "ESIC_EMPLOYEE" | "ESIC_EMPLOYER";
export type CalcType = "FIXED" | "PERCENT" | "BALANCE" | "STATUTORY";

export interface PayComponent {
  id: string;
  code: string;
  name: string;
  kind: ComponentKind;
  statutory_code: StatutoryCode | null;
  taxable: boolean;
  in_pf_wages: boolean;
  in_esic_wages: boolean;
  prorate: boolean;
  payslip_order: number;
  status: "ACTIVE" | "INACTIVE";
  version: number;
}

export type PayComponentInput = Omit<PayComponent, "id" | "status" | "version">;
export type PayComponentPatch = Partial<Pick<PayComponent, "name" | "taxable" | "in_pf_wages" | "in_esic_wages" | "prorate" | "payslip_order" | "status">>;

export interface StructureLineInput {
  component_id: string;
  calc_type: CalcType;
  amount?: Money | null;
  percent?: string | null;
  base?: "CTC" | "COMPONENT" | null;
  base_component_id?: string | null;
  min_amount?: Money | null;
  max_amount?: Money | null;
}

export interface StructureLine extends StructureLineInput {
  id: string;
  component_code: string;
  component_name: string;
  component_kind: ComponentKind;
  sequence: number;
}

export interface SalaryStructure {
  id: string;
  name: string;
  description: string | null;
  legal_entity_id: string | null;
  status: string;
  supersedes_id: string | null;
  lines: StructureLine[];
  /** People whose current salary uses this version. */
  employees: number;
}

export interface StructureInput {
  name: string;
  description?: string | null;
  legal_entity_id?: string | null;
  lines: StructureLineInput[];
}

export interface BreakupLine {
  code: string;
  name: string;
  kind: ComponentKind;
  monthly: Money;
  annual: Money;
}

export interface Breakup {
  annual_ctc: Money;
  monthly_ctc: Money;
  lines: BreakupLine[];
  gross: Money;
  employer_contributions: Money;
  reimbursements: Money;
  deductions: Money;
  net_before_tax: Money;
  pf_wages: Money;
  esic_wages: Money;
  esic_applies: boolean;
  /** Built on statutory values the payroll reviewer hasn't verified yet. */
  provisional: boolean;
  warnings: string[];
}

export interface Compensation {
  id: string;
  employment_id: string;
  structure_id: string;
  structure_name: string;
  /** Null when the salary was sealed with a key that is no longer configured (see `error`). */
  annual_ctc: Money | null;
  error?: string | null;
  currency: string;
  effective_from: string;
  effective_to: string | null;
  reason: string | null;
  note: string | null;
  recorded_by_name: string | null;
  recorded_at: string;
}

export interface CompensationDetail {
  employment_id: string;
  current: Compensation | null;
  breakup: Breakup | null;
  breakup_error: string | null;
  history: Compensation[];
}

export interface CompensationInput {
  structure_id: string;
  annual_ctc: Money;
  effective_from: string;
  reason?: string | null;
  note?: string | null;
}

export interface SalaryRow {
  employment_id: string;
  employee_number: string;
  name: string;
  legal_entity_id: string;
  company: string | null;
  department: string | null;
  designation: string | null;
  employment_state: string;
  annual_ctc: Money | null;
  structure_name: string | null;
  effective_from: string | null;
}

const P = "/v1/payroll";

export const payrollApi = {
  statutoryRules: () => api.get<StatutoryRule[]>(`${P}/statutory-rules`),
  loadIndiaDefaults: () => api.post<StatutoryRule[]>(`${P}/statutory-rules/india-defaults`, {}),
  createStatutoryRule: (body: { rule_code: string; value: string; effective_from: string; source: string }) =>
    api.post<StatutoryRule>(`${P}/statutory-rules`, body),
  verifyStatutoryRule: (id: string) => api.post<StatutoryRule>(`${P}/statutory-rules/${id}/verify`, {}),

  components: () => api.get<PayComponent[]>(`${P}/components`),
  createComponent: (body: PayComponentInput) => api.post<PayComponent>(`${P}/components`, body),
  updateComponent: (id: string, body: PayComponentPatch) => api.patch<PayComponent>(`${P}/components/${id}`, body),
  createStandardComponents: () => api.post<PayComponent[]>(`${P}/components/standard`, {}),

  structures: () => api.get<SalaryStructure[]>(`${P}/structures`),
  createStructure: (body: StructureInput) => api.post<SalaryStructure>(`${P}/structures`, body),
  /** Saves a new version; salaries already on the old version keep it until revised. */
  replaceStructure: (id: string, body: StructureInput) => api.put<SalaryStructure>(`${P}/structures/${id}`, body),
  deactivateStructure: (id: string) => api.post<SalaryStructure>(`${P}/structures/${id}/deactivate`, {}),
  createStandardStructure: () => api.post<SalaryStructure>(`${P}/structures/standard`, {}),
  preview: (body: { annual_ctc: Money; lines: StructureLineInput[]; on?: string }) => api.post<Breakup>(`${P}/structures/preview`, body),

  salaries: (legalEntityId?: string) =>
    api.get<SalaryRow[]>(`${P}/salaries${legalEntityId ? `?legal_entity_id=${legalEntityId}` : ""}`),
  compensation: (employmentId: string) => api.get<CompensationDetail>(`${P}/employees/${employmentId}/compensation`),
  setCompensation: (employmentId: string, body: CompensationInput) =>
    api.post<Compensation>(`${P}/employees/${employmentId}/compensation`, body),
};

/** Lines as the structure editor and preview send them. */
export function lineInput(l: StructureLine): StructureLineInput {
  return {
    component_id: l.component_id, calc_type: l.calc_type, amount: l.amount ?? null, percent: l.percent ?? null,
    base: l.base ?? null, base_component_id: l.base_component_id ?? null, min_amount: l.min_amount ?? null, max_amount: l.max_amount ?? null,
  };
}

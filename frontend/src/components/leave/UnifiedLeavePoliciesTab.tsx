import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Shield,
  Plus,
  PenLine,
  Trash2,
  Building2,
  Sparkles,
} from "lucide-react";
import { leaveApi, type UnifiedLeavePolicy } from "../../api/leave";
import { orgApi, type OrgUnit } from "../../api/org";
import { Sheet, ConfirmDialog } from "../ui/Overlay";
import { Skeleton, EmptyState } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

const PRESET_COLORS = [
  "#3B82F6", // Blue
  "#10B981", // Emerald
  "#F59E0B", // Amber
  "#EF4444", // Red
  "#8B5CF6", // Purple
  "#EC4899", // Pink
  "#06B6D4", // Cyan
  "#6366F1", // Indigo
];

export function UnifiedLeavePoliciesTab({
  policies: propPolicies,
  loading: propLoading,
  createPolicyOpen,
  onCloseCreatePolicy,
}: {
  policies?: UnifiedLeavePolicy[];
  loading?: boolean;
  createPolicyOpen?: boolean;
  onCloseCreatePolicy?: () => void;
} = {}) {
  const qc = useQueryClient();
  const toast = useToast();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [daysPerYear, setDaysPerYear] = useState("12");
  const [accrualType, setAccrualType] = useState<"ANNUAL_UPFRONT" | "MONTHLY_PRORATE">("ANNUAL_UPFRONT");
  const [orgUnitId, setOrgUnitId] = useState<string>("");
  const [applySandwichRule, setApplySandwichRule] = useState(false);
  const [probationEligible, setProbationEligible] = useState(false);
  const [carryForward, setCarryForward] = useState(false);
  const [maxCarryForward, setMaxCarryForward] = useState("");
  const [encashable, setEncashable] = useState(false);
  const [color, setColor] = useState("#3B82F6");
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Queries
  const policies = useQuery<UnifiedLeavePolicy[]>({
    queryKey: ["unified-leave-policies"],
    queryFn: () => leaveApi.listUnifiedPolicies(),
    staleTime: 5 * 60 * 1000,
    placeholderData: (prev) => prev,
  });

  const orgUnits = useQuery<OrgUnit[]>({
    queryKey: ["org-units"],
    queryFn: () => orgApi.listOrgUnits(),
    enabled: sheetOpen,
  });

  const resetForm = () => {
    setEditingId(null);
    setName("");
    setCode("");
    setDaysPerYear("12");
    setAccrualType("ANNUAL_UPFRONT");
    setOrgUnitId("");
    setApplySandwichRule(false);
    setProbationEligible(false);
    setCarryForward(false);
    setMaxCarryForward("");
    setEncashable(false);
    setColor("#3B82F6");
    setShowAdvanced(false);
  };

  const openCreate = () => {
    resetForm();
    setSheetOpen(true);
  };

  useEffect(() => {
    if (createPolicyOpen) {
      openCreate();
      onCloseCreatePolicy?.();
    }
  }, [createPolicyOpen]);

  const openEdit = (p: UnifiedLeavePolicy) => {
    setEditingId(p.leave_type_id);
    setName(p.name);
    setCode(p.code);
    setDaysPerYear(String(p.days_per_year));
    setAccrualType(p.accrual_type === "MONTHLY_PRORATE" ? "MONTHLY_PRORATE" : "ANNUAL_UPFRONT");
    setOrgUnitId(p.org_unit_id ?? "");
    setApplySandwichRule(p.apply_sandwich_rule);
    setProbationEligible(p.probation_eligible);
    setCarryForward(p.carry_forward);
    setMaxCarryForward(p.max_carry_forward_days != null ? String(p.max_carry_forward_days) : "");
    setEncashable(p.encashable);
    setColor(p.color || "#3B82F6");
    setShowAdvanced(p.carry_forward || p.encashable);
    setSheetOpen(true);
  };

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["unified-leave-policies"] });
    qc.invalidateQueries({ queryKey: ["leave-types"] });
    qc.invalidateQueries({ queryKey: ["leave-balances"] });
    qc.invalidateQueries({ queryKey: ["leave-policy-sets"] });
    qc.invalidateQueries({ queryKey: ["leave-bucket-policies"] });
    qc.invalidateQueries({ queryKey: ["leave-policy-assignments"] });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      return leaveApi.createUnifiedPolicy({
        name: name.trim(),
        code: code.trim() || undefined,
        days_per_year: Number(daysPerYear) || 0,
        accrual_type: accrualType,
        org_unit_id: orgUnitId || null,
        apply_sandwich_rule: applySandwichRule,
        probation_eligible: probationEligible,
        carry_forward: carryForward,
        max_carry_forward_days: carryForward && maxCarryForward ? Number(maxCarryForward) : null,
        encashable: encashable,
        color: color,
      });
    },
    onSuccess: (saved) => {
      invalidateAll();
      toast.success(
        editingId ? "Policy updated" : "Policy created & balances deposited",
        `${saved.name} assigned to ${saved.org_unit_name || "All Departments"}`
      );
      setSheetOpen(false);
      resetForm();
    },
    onError: (e) => toast.error("Couldn’t save leave policy", errorMessage(e)),
  });

  const deleteMutation = useMutation({
    mutationFn: (typeId: string) => leaveApi.deleteUnifiedPolicy(typeId),
    onSuccess: () => {
      invalidateAll();
      toast.success("Policy removed");
      setConfirmDeleteId(null);
    },
    onError: (e) => toast.error("Couldn’t remove policy", errorMessage(e)),
  });

  const policyList = propPolicies ?? policies.data ?? [];
  const isLoading = propLoading !== undefined ? propLoading : (policies.isPending && policyList.length === 0);
  const ouList = orgUnits.data ?? [];
  const canSave = name.trim() !== "" && Number(daysPerYear) >= 0;

  return (
    <div className="space-y-6">
      {/* ─── Top Header Action Card ─── */}
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="card-title mb-1 flex items-center gap-2">
              <Shield size={18} className="text-primary" /> Leave policies
            </h3>
            <p className="text-xs text-fg-subtle">
              Configure leave quotas, accrual schedules, department assignments, and policy rules.
            </p>
          </div>
          <button className="btn-primary" onClick={openCreate}>
            <Plus size={15} /> New leave policy
          </button>
        </div>

        {/* ─── Policies Roster Table ─── */}
        <div className="mt-5">
          {isLoading && policyList.length === 0 ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-14 rounded-lg" />
              ))}
            </div>
          ) : policyList.length === 0 ? (
            <EmptyState
              icon={Sparkles}
              title="No leave policies configured yet"
              description="Click '+ New leave policy' to create your first policy with automatic balance allocation."
              action={
                <button className="btn-primary" onClick={openCreate}>
                  <Plus size={15} /> New leave policy
                </button>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="border-b border-line text-xs font-normal text-fg-subtle">
                    <th className="pb-3 font-normal">Leave name</th>
                    <th className="pb-3 font-normal">Quota</th>
                    <th className="pb-3 font-normal">Accrual schedule</th>
                    <th className="pb-3 font-normal">Department</th>
                    <th className="pb-3 font-normal text-center">Sandwich rule</th>
                    <th className="pb-3 font-normal text-center">Probation</th>
                    <th className="pb-3 font-normal text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {policyList.map((p) => (
                    <tr key={p.id} className="transition-colors hover:bg-muted/40">
                      <td className="py-3">
                        <span className="inline-flex items-center gap-2.5 font-medium text-fg">
                          <span
                            className="h-2.5 w-2.5 shrink-0 rounded-full"
                            style={{ background: p.color }}
                          />
                          {p.name}
                          <span className="font-mono text-xs text-fg-subtle">({p.code})</span>
                        </span>
                      </td>
                      <td className="py-3 tabular-nums text-fg">
                        <b>{p.days_per_year}</b> days / yr
                      </td>
                      <td className="py-3">
                        {p.accrual_type === "ANNUAL_UPFRONT" ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                            Annual upfront
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-300">
                            Monthly ({roundAccrual(p.days_per_year)}/mo)
                          </span>
                        )}
                      </td>
                      <td className="py-3 text-fg-muted">
                        <span className="inline-flex items-center gap-1.5">
                          <Building2 size={13} className="text-fg-subtle" />
                          {p.org_unit_name || "All Departments"}
                        </span>
                      </td>
                      <td className="py-3 text-center">
                        {p.apply_sandwich_rule ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2 py-0.5 text-xs font-medium text-indigo-700 dark:text-indigo-300">
                            ✓ Applied
                          </span>
                        ) : (
                          <span className="text-xs text-fg-subtle">—</span>
                        )}
                      </td>
                      <td className="py-3 text-center">
                        {p.probation_eligible ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-300">
                            Allowed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                            🔒 After probation
                          </span>
                        )}
                      </td>
                      <td className="py-3 text-right">
                        <div className="inline-flex items-center gap-1">
                          <button
                            type="button"
                            className="btn-secondary btn-sm"
                            onClick={() => openEdit(p)}
                            title="Edit policy"
                          >
                            <PenLine size={13} /> Edit
                          </button>
                          <button
                            type="button"
                            className="btn-secondary btn-sm text-red-600 hover:bg-red-500/10 dark:text-red-400"
                            onClick={() => setConfirmDeleteId(p.leave_type_id)}
                            title="Remove policy"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ─── 1-Screen Policy Setup Sheet ─── */}
      <Sheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        title={editingId ? "Edit Leave Policy" : "New Leave Policy"}
        description="Set up quota, accrual schedule, department assignment, and sandwich rules in one place."
        footer={
          <>
            <button className="btn-secondary" onClick={() => setSheetOpen(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              disabled={!canSave || saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {saveMutation.isPending ? "Saving & depositing…" : "Save Policy & Deposit Balances"}
            </button>
          </>
        }
      >
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSave) saveMutation.mutate();
          }}
        >
          {/* Leave Name & Code */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="label" htmlFor="policy-name">
                Leave Name <span className="text-red-500">*</span>
              </label>
              <input
                id="policy-name"
                className="input"
                placeholder="e.g. Casual Leave"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!code || code === name.slice(0, 3).toUpperCase()) {
                    setCode(e.target.value.replace(/[^A-Za-z]/g, "").slice(0, 4).toUpperCase());
                  }
                }}
                required
              />
            </div>
            <div>
              <label className="label" htmlFor="policy-code">
                Code <span className="text-red-500">*</span>
              </label>
              <input
                id="policy-code"
                className="input font-mono uppercase"
                placeholder="CL"
                maxLength={10}
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                required
              />
            </div>
          </div>

          {/* Color Picker */}
          <div>
            <label className="label">Badge Color</label>
            <div className="flex items-center gap-2">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`h-6 w-6 rounded-full border-2 transition-transform ${
                    color === c ? "scale-110 border-fg" : "border-transparent"
                  }`}
                  style={{ background: c }}
                  onClick={() => setColor(c)}
                  aria-label={`Color ${c}`}
                />
              ))}
            </div>
          </div>

          {/* Quota */}
          <div>
            <label className="label" htmlFor="policy-quota">
              Yearly Quota (Days / Year) <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <input
                id="policy-quota"
                type="number"
                step="0.5"
                min="0"
                className="input pr-16"
                placeholder="12"
                value={daysPerYear}
                onChange={(e) => setDaysPerYear(e.target.value)}
                required
              />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-fg-subtle">
                days / yr
              </span>
            </div>
          </div>

          {/* Accrual Schedule */}
          <div>
            <label className="label">Accrual Schedule</label>
            <div className="grid grid-cols-2 gap-3">
              <label
                className={`flex cursor-pointer flex-col rounded-xl border p-3 transition-colors ${
                  accrualType === "ANNUAL_UPFRONT"
                    ? "border-primary bg-primary/5 text-primary"
                    : "border-line bg-panel hover:bg-muted/40"
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="accrual-type"
                    className="radio"
                    checked={accrualType === "ANNUAL_UPFRONT"}
                    onChange={() => setAccrualType("ANNUAL_UPFRONT")}
                  />
                  <span className="text-[13px] font-medium text-fg">Annual Upfront</span>
                </div>
                <span className="mt-1 text-xs text-fg-subtle">
                  Full {daysPerYear || 12} days deposited on Day 1.
                </span>
              </label>

              <label
                className={`flex cursor-pointer flex-col rounded-xl border p-3 transition-colors ${
                  accrualType === "MONTHLY_PRORATE"
                    ? "border-primary bg-primary/5 text-primary"
                    : "border-line bg-panel hover:bg-muted/40"
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="accrual-type"
                    className="radio"
                    checked={accrualType === "MONTHLY_PRORATE"}
                    onChange={() => setAccrualType("MONTHLY_PRORATE")}
                  />
                  <span className="text-[13px] font-medium text-fg">Monthly</span>
                </div>
                <span className="mt-1 text-xs text-fg-subtle">
                  {roundAccrual(Number(daysPerYear))} days credited each month.
                </span>
              </label>
            </div>
          </div>

          {/* Department Assignment */}
          <div>
            <label className="label" htmlFor="policy-dept">
              Department Assignment
            </label>
            <select
              id="policy-dept"
              className="input"
              value={orgUnitId}
              onChange={(e) => setOrgUnitId(e.target.value)}
            >
              <option value="">All Departments (Company-wide)</option>
              {ouList.map((ou) => (
                <option key={ou.id} value={ou.id}>
                  {ou.name}
                </option>
              ))}
            </select>
            <p className="hint">
              When saved, balances will instantly be deposited to every employee in this department.
            </p>
          </div>

          {/* Sandwich Rule Toggle */}
          <div className="rounded-xl border border-line bg-panel p-3.5">
            <label className="flex cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                className="checkbox mt-0.5"
                checked={applySandwichRule}
                onChange={(e) => setApplySandwichRule(e.target.checked)}
              />
              <div className="min-w-0 flex-1">
                <span className="text-[13px] font-medium text-fg">
                  Apply Sandwich Rule
                </span>
                <p className="mt-0.5 text-xs text-fg-subtle">
                  If an employee requests leave for Friday and the following Monday, the weekend (Saturday & Sunday) and any intervening public holidays are also counted as leave (4 days total).
                </p>
              </div>
            </label>
          </div>

          {/* Probation Handling Toggle */}
          <div className="rounded-xl border border-line bg-panel p-3.5">
            <span className="text-[13px] font-medium text-fg">
              Allow during probation?
            </span>
            <div className="mt-2 flex items-center gap-4">
              <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-fg">
                <input
                  type="radio"
                  name="probation-allowed"
                  className="radio"
                  checked={probationEligible}
                  onChange={() => setProbationEligible(true)}
                />
                Yes (instant balance on Day 1)
              </label>
              <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-fg">
                <input
                  type="radio"
                  name="probation-allowed"
                  className="radio"
                  checked={!probationEligible}
                  onChange={() => setProbationEligible(false)}
                />
                No (unlocks after probation)
              </label>
            </div>
            {!probationEligible && (
              <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                🔒 Probationers will see a friendly notice: <i>"Leaves unlock on [Date] after probation"</i> instead of a 0-balance error.
              </p>
            )}
          </div>

          {/* Advanced Rules Toggle */}
          <div>
            <button
              type="button"
              className="text-xs font-medium text-primary hover:underline"
              onClick={() => setShowAdvanced(!showAdvanced)}
            >
              {showAdvanced ? "− Hide carry forward & encashment rules" : "+ Carry forward & encashment rules"}
            </button>

            {showAdvanced && (
              <div className="mt-3 space-y-3 rounded-xl border border-line bg-panel p-3.5">
                {/* Carry Forward */}
                <div className="flex items-center justify-between gap-3">
                  <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-fg">
                    <input
                      type="checkbox"
                      className="checkbox"
                      checked={carryForward}
                      onChange={(e) => setCarryForward(e.target.checked)}
                    />
                    Carry forward unused balance to next year
                  </label>
                  {carryForward && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-fg-subtle">Max cap:</span>
                      <input
                        type="number"
                        min="0"
                        className="input w-16 px-2 text-xs"
                        placeholder="cap"
                        value={maxCarryForward}
                        onChange={(e) => setMaxCarryForward(e.target.value)}
                        title="Blank = uncapped"
                      />
                    </div>
                  )}
                </div>

                {/* Encashment */}
                <div>
                  <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-fg">
                    <input
                      type="checkbox"
                      className="checkbox"
                      checked={encashable}
                      onChange={(e) => setEncashable(e.target.checked)}
                    />
                    Allow leave encashment (cash payout)
                  </label>
                </div>
              </div>
            )}
          </div>
        </form>
      </Sheet>

      {/* ─── Confirm Delete Dialog ─── */}
      <ConfirmDialog
        open={!!confirmDeleteId}
        onClose={() => setConfirmDeleteId(null)}
        onConfirm={() => {
          if (confirmDeleteId) deleteMutation.mutate(confirmDeleteId);
        }}
        title="Remove leave policy"
        description="Are you sure you want to remove this leave policy? Past leave requests and historical ledger records will be preserved."
        confirmLabel="Remove policy"
        loading={deleteMutation.isPending}
      />
    </div>
  );
}

function roundAccrual(days: number): string {
  if (!days || isNaN(days)) return "1";
  return (days / 12).toFixed(1);
}

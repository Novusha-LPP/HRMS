import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  FileText,
  Plus,
  Shield,
  Building2,
  Users,
  FolderTree,
  Trash2,
} from "lucide-react";
import {
  leaveApi,
  type LeavePolicySet,
  type LeaveBucketPolicy,
  type LeavePolicyAssignment,
  type LeaveBalanceBucket,
  type LeaveType,
  type LeaveTypeBucketMapping,
} from "../../api/leave";
import { orgApi, type LegalEntity, type OrgUnit } from "../../api/org";
import { peopleApi } from "../../api/people";
import { usePeopleDirectory } from "../../lib/usePeopleDirectory";
import { Sheet, ConfirmDialog } from "../ui/Overlay";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

export interface LeavePolicySetsTabProps {
  createSetOpen?: boolean;
  onOpenCreateSet?: () => void;
  onCloseCreateSet?: () => void;
}

export function LeavePolicySetsTab({
  createSetOpen: controlledCreateSetOpen,
  onOpenCreateSet,
  onCloseCreateSet,
}: LeavePolicySetsTabProps = {}) {
  const qc = useQueryClient();
  const toast = useToast();

  const [selectedSetId, setSelectedSetId] = useState<string>("");
  const [internalCreateSetOpen, setInternalCreateSetOpen] = useState(false);
  const isCreateSetOpen = controlledCreateSetOpen !== undefined ? controlledCreateSetOpen : internalCreateSetOpen;
  const setCreateSetOpen = (open: boolean) => {
    if (open) {
      if (onOpenCreateSet) onOpenCreateSet();
      else setInternalCreateSetOpen(true);
    } else {
      if (onCloseCreateSet) onCloseCreateSet();
      else setInternalCreateSetOpen(false);
    }
  };

  const [setName, setSetName] = useState("");
  const [setDescription, setSetDescription] = useState("");
  const [setIsDefault, setSetIsDefault] = useState(false);

  // Leave Entitlement Rule Sheet state
  const [policySheetOpen, setPolicySheetOpen] = useState(false);
  const [selectedTypeId, setSelectedTypeId] = useState("");
  const [accrualType, setAccrualType] = useState<"ANNUAL_UPFRONT" | "MONTHLY_PRORATE" | "NONE">(
    "MONTHLY_PRORATE"
  );
  const [daysPerYear, setDaysPerYear] = useState("18");
  const [carryForward, setCarryForward] = useState(true);
  const [maxCarryForward, setMaxCarryForward] = useState("10");
  const [lapseEnabled, setLapseEnabled] = useState(true);
  const [encashmentEnabled, setEncashmentEnabled] = useState(false);
  const [maxEncashment, setMaxEncashment] = useState("5");
  const [probationEligible, setProbationEligible] = useState(false);
  const [minServiceMonths, setMinServiceMonths] = useState("0");

  // Assignment Sheet state
  const [assignSheetOpen, setAssignSheetOpen] = useState(false);
  const [targetType, setTargetType] = useState<"LEGAL_ENTITY" | "ORG_UNIT" | "EMPLOYEE">(
    "ORG_UNIT"
  );
  const [targetLegalEntityId, setTargetLegalEntityId] = useState("");
  const [targetOrgUnitId, setTargetOrgUnitId] = useState("");
  const [targetEmploymentId, setTargetEmploymentId] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(
    format(new Date(), "yyyy-01-01")
  );
  const [effectiveTo, setEffectiveTo] = useState("");

  const [confirmDeletePolicyId, setConfirmDeletePolicyId] = useState<string | null>(null);
  const [confirmDeleteAssignmentId, setConfirmDeleteAssignmentId] = useState<string | null>(null);

  // Queries
  const policySets = useQuery<LeavePolicySet[]>({
    queryKey: ["leave-policy-sets"],
    queryFn: () => leaveApi.listPolicySets(),
  });

  const buckets = useQuery<LeaveBalanceBucket[]>({
    queryKey: ["leave-buckets"],
    queryFn: () => leaveApi.listBuckets(),
  });

  const leaveTypes = useQuery<LeaveType[]>({
    queryKey: ["leave-types"],
    queryFn: () => leaveApi.listTypes(),
  });

  const bucketMappings = useQuery<LeaveTypeBucketMapping[]>({
    queryKey: ["leave-bucket-mappings"],
    queryFn: () => leaveApi.listBucketMappings(),
  });

  const legalEntities = useQuery<LegalEntity[]>({
    queryKey: ["legal-entities"],
    queryFn: () => orgApi.listLegalEntities(),
  });

  const orgUnits = useQuery<OrgUnit[]>({
    queryKey: ["org-units"],
    queryFn: () => orgApi.listOrgUnits(),
  });

  const employees = useQuery({
    queryKey: ["employees-picker"],
    queryFn: () => peopleApi.listAllEmployees(),
  });
  const directory = usePeopleDirectory(true);

  const setList = policySets.data ?? [];
  const activeSet = setList.find((s) => s.id === selectedSetId) || setList[0] || null;
  const activeSetId = activeSet?.id ?? "";

  const bucketPolicies = useQuery<LeaveBucketPolicy[]>({
    queryKey: ["leave-bucket-policies", activeSetId],
    queryFn: () => leaveApi.listBucketPolicies(activeSetId),
    enabled: !!activeSetId,
  });

  const assignments = useQuery<LeavePolicyAssignment[]>({
    queryKey: ["leave-policy-assignments"],
    queryFn: () => leaveApi.listPolicyAssignments(),
  });

  // Mutations
  const createSet = useMutation({
    mutationFn: () =>
      leaveApi.createPolicySet({
        name: setName.trim(),
        description: setDescription.trim() || undefined,
        is_default: setIsDefault,
      }),
    onSuccess: (newSet) => {
      qc.invalidateQueries({ queryKey: ["leave-policy-sets"] });
      toast.success("Policy set created", newSet.name);
      setSelectedSetId(newSet.id);
      setSetName("");
      setSetDescription("");
      setSetIsDefault(false);
      setCreateSetOpen(false);
    },
    onError: (e) => toast.error("Couldn’t create policy set", errorMessage(e)),
  });

  // A "bucket" is just the ledger's internal accounting unit — almost always
  // one per leave type. Rather than make the user create a bucket and map a
  // leave type to it by hand (the old flow), we resolve or silently create
  // that 1:1 bucket here, so this sheet only ever talks about leave types.
  const resolveOrCreateBucketForType = async (type: LeaveType): Promise<string> => {
    const existingMapping = (bucketMappings.data ?? []).find((m) => m.leave_type_id === type.id);
    if (existingMapping) return existingMapping.bucket_id;

    const code = type.code.trim().toUpperCase();
    const reusableBucket = (buckets.data ?? []).find((b) => {
      const bCode = b.code.toUpperCase();
      return bCode === code || bCode === `${code}_BAL`;
    });
    const bucket = reusableBucket ?? (await leaveApi.createBucket({ name: type.name, code, is_unlimited: false }));
    await leaveApi.createBucketMapping({ leave_type_id: type.id, bucket_id: bucket.id });
    return bucket.id;
  };

  const saveBucketPolicy = useMutation({
    mutationFn: async () => {
      const type = (leaveTypes.data ?? []).find((t) => t.id === selectedTypeId);
      if (!type) throw new Error("Select a leave type");
      const resolvedBucketId = await resolveOrCreateBucketForType(type);
      return leaveApi.createBucketPolicy(activeSetId, {
        bucket_id: resolvedBucketId,
        accrual_type: accrualType,
        days_per_year: Number(daysPerYear),
        carry_forward_enabled: carryForward,
        max_carry_forward_days: carryForward && maxCarryForward ? Number(maxCarryForward) : null,
        lapse_enabled: lapseEnabled,
        encashment_enabled: encashmentEnabled,
        max_encashment_days: encashmentEnabled && maxEncashment ? Number(maxEncashment) : null,
        probation_eligible: probationEligible,
        min_service_months: Number(minServiceMonths) || 0,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-bucket-policies", activeSetId] });
      qc.invalidateQueries({ queryKey: ["leave-buckets"] });
      qc.invalidateQueries({ queryKey: ["leave-bucket-mappings"] });
      toast.success("Leave entitlement rule saved");
      setPolicySheetOpen(false);
    },
    onError: (e) => toast.error("Couldn’t save leave rule", errorMessage(e)),
  });

  const deleteBucketPolicy = useMutation({
    mutationFn: (id: string) => leaveApi.deleteBucketPolicy(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-bucket-policies", activeSetId] });
      toast.success("Bucket rule removed");
      setConfirmDeletePolicyId(null);
    },
    onError: (e) => toast.error("Couldn’t remove rule", errorMessage(e)),
  });

  const createAssignment = useMutation({
    mutationFn: () =>
      leaveApi.createPolicyAssignment({
        leave_policy_set_id: activeSetId,
        effective_from: effectiveFrom,
        effective_to: effectiveTo || undefined,
        legal_entity_id: targetType === "LEGAL_ENTITY" ? targetLegalEntityId : undefined,
        org_unit_id: targetType === "ORG_UNIT" ? targetOrgUnitId : undefined,
        employment_id: targetType === "EMPLOYEE" ? targetEmploymentId : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-policy-assignments"] });
      toast.success("Policy set assigned successfully");
      setAssignSheetOpen(false);
    },
    onError: (e) => toast.error("Couldn’t assign policy set", errorMessage(e)),
  });

  const deleteAssignment = useMutation({
    mutationFn: (id: string) => leaveApi.deletePolicyAssignment(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-policy-assignments"] });
      toast.success("Assignment ended");
      setConfirmDeleteAssignmentId(null);
    },
    onError: (e) => toast.error("Couldn’t remove assignment", errorMessage(e)),
  });

  const bpList = bucketPolicies.data ?? [];
  const assignmentList = (assignments.data ?? []).filter(
    (a) => a.leave_policy_set_id === activeSetId
  );
  const mappingList = bucketMappings.data ?? [];
  const typeList = (leaveTypes.data ?? []).filter((t) => !t.is_comp_off);

  // Configured bucket IDs in this set
  const configuredBucketIds = new Set(bpList.map((bp) => bp.bucket_id));
  const typeToBucketId = new Map(mappingList.map((m) => [m.leave_type_id, m.bucket_id]));
  const unconfiguredTypes = typeList.filter((t) => {
    const resolvedBucketId = typeToBucketId.get(t.id);
    return !resolvedBucketId || !configuredBucketIds.has(resolvedBucketId);
  });

  return (
    <div className="space-y-6">
      {/* ─── Top Policy Set Selector ─── */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-panel px-4 py-3">
        <div>
          <label htmlFor="active-policy-set-select" className="label text-xs">Active Leave Policy Set</label>
          <select
            id="active-policy-set-select"
            className="input text-xs font-medium"
            value={activeSetId}
            onChange={(e) => setSelectedSetId(e.target.value)}
          >
            {setList.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} {s.is_default ? "★ (Tenant Default)" : ""}
              </option>
            ))}
          </select>
        </div>

        {activeSet && (
          <div className="flex items-center gap-2">
            {activeSet.is_default && (
              <span className="badge badge-success text-[11px]">Tenant Default Policy</span>
            )}
            {activeSet.description && (
              <span className="text-xs text-fg-subtle">· {activeSet.description}</span>
            )}
          </div>
        )}
      </div>

      {!activeSet ? (
        <div className="card p-10">
          <EmptyState
            icon={FileText}
            title="No policy sets created"
            description={'Create your first leave policy set using the "+ New policy set" button above to define accrual rules and entitlement limits.'}
          />
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-12">
          {/* ─── Left Column: Bucket Entitlement Policies (7 cols) ─── */}
          <div className="space-y-4 lg:col-span-7">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-fg">
                  Leave Entitlement Rules ({activeSet.name})
                </h3>
                <p className="text-xs text-fg-subtle">
                  Pick a leave type and set its accrual frequency, annual quota, carry-forward and encashment for this policy set.
                </p>
              </div>
              <button
                className="btn-primary btn-sm"
                onClick={() => {
                  setSelectedTypeId(unconfiguredTypes[0]?.id || "");
                  setPolicySheetOpen(true);
                }}
                disabled={unconfiguredTypes.length === 0}
              >
                <Plus size={13} /> Add Leave Rule
              </button>
            </div>

            {bucketPolicies.isPending ? (
              <div className="space-y-3">
                {[0, 1].map((i) => (
                  <Skeleton key={i} className="h-28 w-full" />
                ))}
              </div>
            ) : bpList.length === 0 ? (
              <div className="card p-8">
                <EmptyState
                  icon={Shield}
                  title="No leave rules configured"
                  description={'Use the "+ Add Leave Rule" button above to define accrual, carry-forward and encashment rules for a leave type.'}
                />
              </div>
            ) : (
              <div className="space-y-3">
                {bpList.map((bp) => (
                  <div
                    key={bp.id}
                    className="card p-4 transition-shadow hover:shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-fg text-sm">
                            {bp.bucket_name}
                          </span>
                          <span className="font-mono text-xs rounded bg-muted px-1.5 py-0.5 text-fg-muted font-bold">
                            {bp.bucket_code}
                          </span>
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                              bp.accrual_type === "MONTHLY_PRORATE"
                                ? "bg-info/10 text-info"
                                : bp.accrual_type === "ANNUAL_UPFRONT"
                                ? "bg-success/10 text-success"
                                : "bg-muted text-fg-subtle"
                            }`}
                          >
                            {bp.accrual_type === "MONTHLY_PRORATE"
                              ? "Monthly Prorate (1/12th)"
                              : bp.accrual_type === "ANNUAL_UPFRONT"
                              ? "Annual Upfront Credit"
                              : "No Auto Accrual"}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-fg-subtle">
                          <b className="font-medium text-fg">{bp.days_per_year} days</b> allocated per year
                        </p>
                      </div>

                      <button
                        className="text-fg-subtle hover:text-danger rounded p-1 transition-colors"
                        onClick={() => setConfirmDeletePolicyId(bp.id)}
                        title="Remove rule"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2 border-t border-line/60 pt-3 text-[11px] text-fg-subtle sm:grid-cols-4">
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-fg-subtle/80">
                          Carry Forward
                        </span>
                        <span className="font-medium text-fg">
                          {bp.carry_forward_enabled
                            ? `Up to ${bp.max_carry_forward_days ?? "∞"} days`
                            : "Disabled"}
                        </span>
                      </div>
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-fg-subtle/80">
                          Year-End Lapse
                        </span>
                        <span className="font-medium text-fg">
                          {bp.lapse_enabled ? "Enabled" : "Disabled"}
                        </span>
                      </div>
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-fg-subtle/80">
                          Encashment
                        </span>
                        <span className="font-medium text-fg">
                          {bp.encashment_enabled
                            ? `Up to ${bp.max_encashment_days ?? "∞"} days`
                            : "Disabled"}
                        </span>
                      </div>
                      <div>
                        <span className="block text-[10px] uppercase tracking-wider text-fg-subtle/80">
                          Probation
                        </span>
                        <span className="font-medium text-fg">
                          {bp.probation_eligible ? "Eligible" : "Excluded"}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ─── Right Column: Policy Assignments & Scope (5 cols) ─── */}
          <div className="space-y-4 lg:col-span-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-fg">Policy Assignments</h3>
                <p className="text-xs text-fg-subtle">
                  Assigned departments, entities, or individuals.
                </p>
              </div>
              <button
                className="btn-primary btn-sm"
                onClick={() => setAssignSheetOpen(true)}
              >
                <Plus size={13} /> Assign
              </button>
            </div>

            {/* Note about 4-tier cascade */}
            <div className="rounded-lg border border-line bg-panel p-3 text-[11px] text-fg-subtle leading-relaxed">
              <span className="font-semibold text-fg flex items-center gap-1.5 mb-1">
                <FolderTree size={13} className="text-accent" /> Cascading Resolution
              </span>
              Assigning a department applies this policy set to all child and grandchild
              departments in the hierarchy automatically. Individual employee assignments override
              all other tiers.
            </div>

            {assignments.isPending ? (
              <div className="space-y-2">
                {[0, 1].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : assignmentList.length === 0 ? (
              <div className="card p-6">
                <EmptyState
                  icon={Users}
                  title="No specific assignments"
                  description={
                    activeSet.is_default
                      ? "This is the tenant default policy set; it covers all employees without a specific assignment."
                      : 'Use the "+ Assign" button above to scope this policy set to a company, department, or individual.'
                  }
                />
              </div>
            ) : (
              <div className="space-y-2">
                {assignmentList.map((asgn) => {
                  const ou = orgUnits.data?.find((u) => u.id === asgn.org_unit_id);
                  const le = legalEntities.data?.find((e) => e.id === asgn.legal_entity_id);
                  const targetLabel = asgn.employment_id
                    ? directory.get(asgn.employment_id) || "Employee Override"
                    : asgn.org_unit_id
                    ? `Dept: ${ou?.name ?? asgn.org_unit_id}`
                    : asgn.legal_entity_id
                    ? `Company: ${le?.name ?? asgn.legal_entity_id}`
                    : "Unknown";

                  return (
                    <div
                      key={asgn.id}
                      className="flex items-center justify-between rounded-lg border border-line bg-surface p-3 text-xs"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 font-medium text-fg">
                          {asgn.org_unit_id ? (
                            <FolderTree size={13} className="text-accent shrink-0" />
                          ) : asgn.legal_entity_id ? (
                            <Building2 size={13} className="text-info shrink-0" />
                          ) : (
                            <Users size={13} className="text-plum shrink-0" />
                          )}
                          <span className="truncate">{targetLabel}</span>
                        </div>
                        <p className="mt-0.5 text-[11px] text-fg-subtle">
                          From {asgn.effective_from}
                          {asgn.effective_to ? ` to ${asgn.effective_to}` : " onwards"}
                        </p>
                      </div>

                      <button
                        className="rounded p-1 text-fg-subtle hover:text-danger transition-colors"
                        onClick={() => setConfirmDeleteAssignmentId(asgn.id)}
                        title="End assignment"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ─── Create Policy Set Sheet ─── */}
      <Sheet
        open={isCreateSetOpen}
        onClose={() => setCreateSetOpen(false)}
        title="Create Leave Policy Set"
        description="A group of entitlement rules for different employee groups (e.g. Corporate Standard, Factory Policy)."
        footer={
          <>
            <button className="btn-secondary" onClick={() => setCreateSetOpen(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => createSet.mutate()}
              disabled={!setName.trim() || createSet.isPending}
            >
              {createSet.isPending ? "Creating…" : "Create Policy Set"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label" htmlFor="ps-name">
              Policy Set Name
            </label>
            <input
              id="ps-name"
              className="input"
              placeholder="e.g. Corporate Standard or Factory Operations"
              value={setName}
              onChange={(e) => setSetName(e.target.value)}
            />
          </div>

          <div>
            <label className="label" htmlFor="ps-desc">
              Description (Optional)
            </label>
            <textarea
              id="ps-desc"
              className="input min-h-[70px]"
              placeholder="Who this policy applies to..."
              value={setDescription}
              onChange={(e) => setSetDescription(e.target.value)}
            />
          </div>

          <label className="flex items-center gap-2 text-xs text-fg cursor-pointer">
            <input
              type="checkbox"
              className="checkbox"
              checked={setIsDefault}
              onChange={(e) => setSetIsDefault(e.target.checked)}
            />
            <span>Set as Tenant Default (used when no specific department or entity matches)</span>
          </label>
        </div>
      </Sheet>

      {/* ─── Add/Edit Leave Entitlement Rule Sheet ─── */}
      <Sheet
        open={policySheetOpen}
        onClose={() => setPolicySheetOpen(false)}
        title="Configure Leave Entitlement"
        description={`Set allocation and carry-forward rules for ${activeSet?.name}.`}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setPolicySheetOpen(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => saveBucketPolicy.mutate()}
              disabled={!selectedTypeId || !daysPerYear || saveBucketPolicy.isPending}
            >
              {saveBucketPolicy.isPending ? "Saving…" : "Save Rule"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label" htmlFor="bp-type">
              Leave Type
            </label>
            <select
              id="bp-type"
              className="input"
              value={selectedTypeId}
              onChange={(e) => setSelectedTypeId(e.target.value)}
            >
              {unconfiguredTypes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.code})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="bp-accrual">
              Accrual Type
            </label>
            <select
              id="bp-accrual"
              className="input"
              value={accrualType}
              onChange={(e) =>
                setAccrualType(
                  e.target.value as "ANNUAL_UPFRONT" | "MONTHLY_PRORATE" | "NONE"
                )
              }
            >
              <option value="MONTHLY_PRORATE">Monthly Prorated (Credits 1/12th each month)</option>
              <option value="ANNUAL_UPFRONT">Annual Upfront (Credits full quota at start of FY)</option>
              <option value="NONE">None (Manual grants or Unpaid only)</option>
            </select>
          </div>

          <div>
            <label className="label" htmlFor="bp-days">
              Days Per Year
            </label>
            <input
              id="bp-days"
              type="number"
              step="0.5"
              min="0"
              className="input"
              value={daysPerYear}
              onChange={(e) => setDaysPerYear(e.target.value)}
            />
          </div>

          <div className="border-t border-line pt-4 space-y-3">
            <h4 className="text-xs font-semibold text-fg">Carry-Forward & Year-End</h4>

            <label className="flex items-center gap-2 text-xs text-fg cursor-pointer">
              <input
                type="checkbox"
                className="checkbox"
                checked={carryForward}
                onChange={(e) => setCarryForward(e.target.checked)}
              />
              <span>Enable Carry-Forward to next financial year</span>
            </label>

            {carryForward && (
              <div>
                <label className="label" htmlFor="bp-max-cf">
                  Max Carry-Forward Days
                </label>
                <input
                  id="bp-max-cf"
                  type="number"
                  step="0.5"
                  className="input"
                  value={maxCarryForward}
                  onChange={(e) => setMaxCarryForward(e.target.value)}
                />
              </div>
            )}

            <label className="flex items-center gap-2 text-xs text-fg cursor-pointer">
              <input
                type="checkbox"
                className="checkbox"
                checked={lapseEnabled}
                onChange={(e) => setLapseEnabled(e.target.checked)}
              />
              <span>Lapse un-carried balance at year-end</span>
            </label>
          </div>

          <div className="border-t border-line pt-4 space-y-3">
            <h4 className="text-xs font-semibold text-fg">Encashment & Eligibility</h4>

            <label className="flex items-center gap-2 text-xs text-fg cursor-pointer">
              <input
                type="checkbox"
                className="checkbox"
                checked={encashmentEnabled}
                onChange={(e) => setEncashmentEnabled(e.target.checked)}
              />
              <span>Allow Encashment of balance</span>
            </label>

            {encashmentEnabled && (
              <div>
                <label className="label" htmlFor="bp-max-enc">
                  Max Encashment Days
                </label>
                <input
                  id="bp-max-enc"
                  type="number"
                  step="0.5"
                  className="input"
                  value={maxEncashment}
                  onChange={(e) => setMaxEncashment(e.target.value)}
                />
              </div>
            )}

            <label className="flex items-center gap-2 text-xs text-fg cursor-pointer">
              <input
                type="checkbox"
                className="checkbox"
                checked={probationEligible}
                onChange={(e) => setProbationEligible(e.target.checked)}
              />
              <span>Eligible during employee probation period</span>
            </label>

            <div>
              <label className="label" htmlFor="bp-min-service">
                Minimum Service Months
              </label>
              <input
                id="bp-min-service"
                type="number"
                min="0"
                className="input"
                value={minServiceMonths}
                onChange={(e) => setMinServiceMonths(e.target.value)}
              />
            </div>
          </div>
        </div>
      </Sheet>

      {/* ─── Assign Policy Set Sheet ─── */}
      <Sheet
        open={assignSheetOpen}
        onClose={() => setAssignSheetOpen(false)}
        title="Assign Leave Policy Set"
        description={`Assign "${activeSet?.name}" to an organizational level.`}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setAssignSheetOpen(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => createAssignment.mutate()}
              disabled={
                !effectiveFrom ||
                (targetType === "LEGAL_ENTITY" && !targetLegalEntityId) ||
                (targetType === "ORG_UNIT" && !targetOrgUnitId) ||
                (targetType === "EMPLOYEE" && !targetEmploymentId) ||
                createAssignment.isPending
              }
            >
              {createAssignment.isPending ? "Assigning…" : "Confirm Assignment"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label">Assignment Target Tier</label>
            <div className="space-y-2 mt-1">
              <label className="flex items-center gap-2 text-xs text-fg cursor-pointer rounded-lg border border-line p-2.5 hover:bg-muted/30">
                <input
                  type="radio"
                  name="target-tier"
                  checked={targetType === "ORG_UNIT"}
                  onChange={() => setTargetType("ORG_UNIT")}
                />
                <div>
                  <span className="font-semibold block">Department / Org Unit</span>
                  <span className="text-[11px] text-fg-subtle">
                    Applies to all employees in this department and its sub-departments.
                  </span>
                </div>
              </label>

              <label className="flex items-center gap-2 text-xs text-fg cursor-pointer rounded-lg border border-line p-2.5 hover:bg-muted/30">
                <input
                  type="radio"
                  name="target-tier"
                  checked={targetType === "LEGAL_ENTITY"}
                  onChange={() => setTargetType("LEGAL_ENTITY")}
                />
                <div>
                  <span className="font-semibold block">Company (Legal Entity)</span>
                  <span className="text-[11px] text-fg-subtle">
                    Company-wide policy for all employees in this entity.
                  </span>
                </div>
              </label>

              <label className="flex items-center gap-2 text-xs text-fg cursor-pointer rounded-lg border border-line p-2.5 hover:bg-muted/30">
                <input
                  type="radio"
                  name="target-tier"
                  checked={targetType === "EMPLOYEE"}
                  onChange={() => setTargetType("EMPLOYEE")}
                />
                <div>
                  <span className="font-semibold block">Individual Employee</span>
                  <span className="text-[11px] text-fg-subtle">
                    Specific override that takes highest precedence over all other tiers.
                  </span>
                </div>
              </label>
            </div>
          </div>

          {targetType === "ORG_UNIT" && (
            <div>
              <label className="label" htmlFor="asgn-ou">
                Select Department
              </label>
              <select
                id="asgn-ou"
                className="input"
                value={targetOrgUnitId}
                onChange={(e) => setTargetOrgUnitId(e.target.value)}
              >
                <option value="">Choose department…</option>
                {(orgUnits.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {targetType === "LEGAL_ENTITY" && (
            <div>
              <label className="label" htmlFor="asgn-le">
                Select Legal Entity
              </label>
              <select
                id="asgn-le"
                className="input"
                value={targetLegalEntityId}
                onChange={(e) => setTargetLegalEntityId(e.target.value)}
              >
                <option value="">Choose legal entity…</option>
                {(legalEntities.data ?? []).map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {targetType === "EMPLOYEE" && (
            <div>
              <label className="label" htmlFor="asgn-emp">
                Select Employee
              </label>
              <select
                id="asgn-emp"
                className="input"
                value={targetEmploymentId}
                onChange={(e) => setTargetEmploymentId(e.target.value)}
              >
                <option value="">Choose employee…</option>
                {(employees.data ?? []).map((e) => (
                  <option key={e.id} value={e.id}>
                    {directory.get(e.id) ?? e.employee_number}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="asgn-from">
                Effective From
              </label>
              <input
                id="asgn-from"
                type="date"
                className="input"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="asgn-to">
                Effective To (Optional)
              </label>
              <input
                id="asgn-to"
                type="date"
                className="input"
                value={effectiveTo}
                onChange={(e) => setEffectiveTo(e.target.value)}
              />
            </div>
          </div>
        </div>
      </Sheet>

      {/* ─── Delete Bucket Policy Dialog ─── */}
      <ConfirmDialog
        open={!!confirmDeletePolicyId}
        onClose={() => setConfirmDeletePolicyId(null)}
        onConfirm={() => {
          if (confirmDeletePolicyId) deleteBucketPolicy.mutate(confirmDeletePolicyId);
        }}
        title="Remove Bucket Rule?"
        description="Employees under this policy set will no longer have an entitlement rule for this bucket."
        confirmLabel="Remove Rule"
      />

      {/* ─── Delete Assignment Dialog ─── */}
      <ConfirmDialog
        open={!!confirmDeleteAssignmentId}
        onClose={() => setConfirmDeleteAssignmentId(null)}
        onConfirm={() => {
          if (confirmDeleteAssignmentId) deleteAssignment.mutate(confirmDeleteAssignmentId);
        }}
        title="End Policy Assignment?"
        description="The assigned target will fall back to higher-level assignments or the tenant default policy set."
        confirmLabel="End Assignment"
      />
    </div>
  );
}

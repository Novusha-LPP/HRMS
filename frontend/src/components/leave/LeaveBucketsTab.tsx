import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Layers,
  Plus,
  Trash2,
  CheckCircle2,
  XCircle,
  Link as LinkIcon,
  Infinity as InfinityIcon,
  Sparkles,
  Check,
  ArrowRight,
} from "lucide-react";
import {
  leaveApi,
  type LeaveBalanceBucket,
  type LeaveTypeBucketMapping,
  type LeaveType,
} from "../../api/leave";
import { Sheet, ConfirmDialog } from "../ui/Overlay";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { useToast, errorMessage } from "../ui/Toast";

export interface BucketPreset {
  name: string;
  code: string;
  is_unlimited: boolean;
  description: string;
  badge: string;
}

export const STANDARD_BUCKET_PRESETS: BucketPreset[] = [
  {
    name: "Privilege / Paid Leave",
    code: "PL_BAL",
    is_unlimited: false,
    description: "Annual earned privilege leave with monthly accrual and carry-forward.",
    badge: "Earned / Privilege",
  },
  {
    name: "Sick Leave",
    code: "SL_BAL",
    is_unlimited: false,
    description: "Dedicated medical and sickness recovery leave balance pool.",
    badge: "Medical",
  },
  {
    name: "Casual Leave",
    code: "CL_BAL",
    is_unlimited: false,
    description: "For short-term unforeseen personal events and urgent matters.",
    badge: "Personal",
  },
  {
    name: "Leave Without Pay (LWP)",
    code: "LWP_BAL",
    is_unlimited: true,
    description: "Unlimited unpaid balance pool for tracking salary deductions.",
    badge: "Unlimited Unpaid",
  },
  {
    name: "Maternity Leave",
    code: "MAT_BAL",
    is_unlimited: false,
    description: "Statutory paid parental leave for female employees (e.g. 26 weeks).",
    badge: "Statutory",
  },
  {
    name: "Paternity Leave",
    code: "PAT_BAL",
    is_unlimited: false,
    description: "Statutory or company parental leave for fathers welcoming a child.",
    badge: "Parental",
  },
  {
    name: "Compensatory Off",
    code: "COMP_BAL",
    is_unlimited: false,
    description: "Accredited balance granted for working on weekends or overtime.",
    badge: "Grant Based",
  },
];

export function LeaveBucketsTab() {
  const qc = useQueryClient();
  const toast = useToast();

  const [createBucketOpen, setCreateBucketOpen] = useState(false);
  const [bucketName, setBucketName] = useState("");
  const [bucketCode, setBucketCode] = useState("");
  const [isUnlimited, setIsUnlimited] = useState(false);

  const [createMappingOpen, setCreateMappingOpen] = useState(false);
  const [mappingTypeId, setMappingTypeId] = useState("");
  const [mappingBucketId, setMappingBucketId] = useState("");

  const [confirmDeleteBucketId, setConfirmDeleteBucketId] = useState<string | null>(null);
  const [confirmDeleteMappingId, setConfirmDeleteMappingId] = useState<string | null>(null);

  // Queries
  const buckets = useQuery<LeaveBalanceBucket[]>({
    queryKey: ["leave-buckets"],
    queryFn: () => leaveApi.listBuckets(),
  });

  const mappings = useQuery<LeaveTypeBucketMapping[]>({
    queryKey: ["leave-bucket-mappings"],
    queryFn: () => leaveApi.listBucketMappings(),
  });

  const leaveTypes = useQuery<LeaveType[]>({
    queryKey: ["leave-types"],
    queryFn: () => leaveApi.listTypes(),
  });

  // Mutations
  const createBucket = useMutation({
    mutationFn: () =>
      leaveApi.createBucket({
        name: bucketName.trim(),
        code: bucketCode.trim().toUpperCase(),
        is_unlimited: isUnlimited,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-buckets"] });
      toast.success("Leave bucket created", `${bucketName} (${bucketCode.toUpperCase()})`);
      setBucketName("");
      setBucketCode("");
      setIsUnlimited(false);
      setCreateBucketOpen(false);
    },
    onError: (e) => toast.error("Couldn’t create bucket", errorMessage(e)),
  });

  const toggleBucketActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      leaveApi.updateBucket(id, { is_active }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-buckets"] });
      toast.success("Bucket status updated");
    },
    onError: (e) => toast.error("Couldn’t update bucket", errorMessage(e)),
  });

  const deleteBucket = useMutation({
    mutationFn: (id: string) => leaveApi.deleteBucket(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-buckets"] });
      toast.success("Bucket archived");
      setConfirmDeleteBucketId(null);
    },
    onError: (e) => toast.error("Couldn’t archive bucket", errorMessage(e)),
  });

  const createMapping = useMutation({
    mutationFn: () =>
      leaveApi.createBucketMapping({
        leave_type_id: mappingTypeId,
        bucket_id: mappingBucketId,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-bucket-mappings"] });
      toast.success("Leave type mapped to bucket");
      setMappingTypeId("");
      setMappingBucketId("");
      setCreateMappingOpen(false);
    },
    onError: (e) => toast.error("Couldn’t create mapping", errorMessage(e)),
  });

  const deleteMapping = useMutation({
    mutationFn: (id: string) => leaveApi.deleteBucketMapping(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-bucket-mappings"] });
      toast.success("Mapping removed");
      setConfirmDeleteMappingId(null);
    },
    onError: (e) => toast.error("Couldn’t remove mapping", errorMessage(e)),
  });

  const createPreset = useMutation({
    mutationFn: (preset: BucketPreset) =>
      leaveApi.createBucket({
        name: preset.name,
        code: preset.code,
        is_unlimited: preset.is_unlimited,
      }),
    onSuccess: (_, preset) => {
      qc.invalidateQueries({ queryKey: ["leave-buckets"] });
      toast.success("Preset bucket created", `${preset.name} (${preset.code})`);
    },
    onError: (e) => toast.error("Couldn’t create bucket", errorMessage(e)),
  });

  const createAllMissing = useMutation({
    mutationFn: async (presets: BucketPreset[]) => {
      for (const p of presets) {
        await leaveApi.createBucket({
          name: p.name,
          code: p.code,
          is_unlimited: p.is_unlimited,
        });
      }
    },
    onSuccess: (_, presets) => {
      qc.invalidateQueries({ queryKey: ["leave-buckets"] });
      toast.success("Standard buckets created", `Added ${presets.length} buckets successfully`);
    },
    onError: (e) => toast.error("Couldn’t create buckets", errorMessage(e)),
  });

  const bucketList = buckets.data ?? [];
  const mappingList = mappings.data ?? [];
  const typeList = leaveTypes.data ?? [];

  // Group mappings by bucket id
  const mappingsByBucket = new Map<string, LeaveTypeBucketMapping[]>();
  for (const m of mappingList) {
    const list = mappingsByBucket.get(m.bucket_id) || [];
    list.push(m);
    mappingsByBucket.set(m.bucket_id, list);
  }

  // Already mapped leave type IDs
  const mappedTypeIds = new Set(mappingList.map((m) => m.leave_type_id));
  const unmappedTypes = typeList.filter((t) => !mappedTypeIds.has(t.id));

  // Codes already existing in this tenant
  const existingCodes = new Set(bucketList.map((b) => b.code.toUpperCase()));
  const missingPresets = STANDARD_BUCKET_PRESETS.filter((p) => !existingCodes.has(p.code.toUpperCase()));

  // Matching unmapped leave types with existing buckets for 1-click auto-mapping
  const autoMappable = useMemo(() => {
    const pairs: { type: LeaveType; bucket: LeaveBalanceBucket }[] = [];
    for (const t of unmappedTypes) {
      const tCode = t.code.toUpperCase();
      const tName = t.name.toLowerCase();
      const matched = bucketList.find((b) => {
        const bCode = b.code.toUpperCase();
        const bName = b.name.toLowerCase();
        if (bCode === tCode || bCode === `${tCode}_BAL` || `${bCode}_BAL` === tCode) return true;
        if (bName.includes(tName) || tName.includes(bName)) return true;
        if (tCode === "PL" && (bCode === "PL_BAL" || bName.includes("paid") || bName.includes("privilege"))) return true;
        if (tCode === "SL" && (bCode === "SL_BAL" || bName.includes("sick"))) return true;
        if (tCode === "CL" && (bCode === "CL_BAL" || bName.includes("casual"))) return true;
        if (tCode === "LWP" && (bCode === "LWP_BAL" || bName.includes("without pay"))) return true;
        if (tCode === "MAT" && (bCode === "MAT_BAL" || bName.includes("maternity"))) return true;
        if (tCode === "PAT" && (bCode === "PAT_BAL" || bName.includes("paternity"))) return true;
        if (tCode === "COMP" && (bCode === "COMP_BAL" || bName.includes("comp"))) return true;
        return false;
      });
      if (matched) {
        pairs.push({ type: t, bucket: matched });
      }
    }
    return pairs;
  }, [unmappedTypes, bucketList]);

  const autoMapMutation = useMutation({
    mutationFn: async (pairs: { type: LeaveType; bucket: LeaveBalanceBucket }[]) => {
      for (const pair of pairs) {
        await leaveApi.createBucketMapping({
          leave_type_id: pair.type.id,
          bucket_id: pair.bucket.id,
        });
      }
    },
    onSuccess: (_, pairs) => {
      qc.invalidateQueries({ queryKey: ["leave-bucket-mappings"] });
      toast.success("Leave types auto-mapped", `Successfully linked ${pairs.length} leave types to balance buckets`);
    },
    onError: (e) => toast.error("Couldn’t auto-map types", errorMessage(e)),
  });

  return (
    <div className="space-y-6">

      {/* ─── Standard Presets Panel ─── */}
      <div className="card p-5 border-brand-500/25 bg-gradient-to-b from-brand-500/[0.04] to-transparent">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-accent" />
              <h3 className="card-title text-[14px]">Standard Enterprise Bucket Presets</h3>
              <span className="badge badge-brand text-[10px]">1-Click Templates</span>
            </div>
            <p className="mt-1 text-xs text-fg-subtle">
              Common leave pools (PL/Privilege, Sick Leave, LWP, Maternity, Paternity, Comp-off). Click to create instantly.
            </p>
          </div>
          {missingPresets.length > 0 && (
            <button
              className="btn-primary btn-sm text-xs"
              onClick={() => createAllMissing.mutate(missingPresets)}
              disabled={createAllMissing.isPending || createPreset.isPending}
            >
              <Sparkles size={13} /> {createAllMissing.isPending ? "Adding all…" : `Add All Missing (${missingPresets.length})`}
            </button>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {STANDARD_BUCKET_PRESETS.map((preset) => {
            const isAdded = existingCodes.has(preset.code.toUpperCase());
            return (
              <div
                key={preset.code}
                className={`flex flex-col justify-between rounded-xl border p-3.5 transition-all ${
                  isAdded
                    ? "border-line bg-muted/20 opacity-80"
                    : "border-line hover:border-brand-500/40 hover:shadow-xs bg-panel"
                }`}
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-medium text-[13px] text-fg leading-snug">
                      {preset.name}
                    </span>
                    <span className="font-mono text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded bg-muted text-fg-muted shrink-0">
                      {preset.code}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-fg-subtle">
                    {preset.description}
                  </p>
                </div>

                <div className="mt-3 flex items-center justify-between pt-2 border-t border-line/60">
                  <span className="text-[10px] font-medium text-fg-muted">
                    {preset.badge}
                  </span>
                  {isAdded ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-success bg-success/10 px-2 py-0.5 rounded-full">
                      <Check size={11} /> Added
                    </span>
                  ) : (
                    <button
                      className="btn-secondary btn-sm h-7 px-2.5 text-[11px]"
                      onClick={() => createPreset.mutate(preset)}
                      disabled={createPreset.isPending || createAllMissing.isPending}
                    >
                      <Plus size={11} /> Add
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ─── Balance Buckets ─── */}
      <div className="card p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="card-title flex items-center gap-2">
              <Layers size={16} className="text-accent" /> Leave Balance Buckets
            </h3>
            <p className="text-xs text-fg-subtle">
              Configured ledger buckets holding leave balances.
            </p>
          </div>
          <button className="btn-primary btn-sm" onClick={() => setCreateBucketOpen(true)}>
            <Plus size={14} /> Add Custom Bucket
          </button>
        </div>

        {buckets.isPending ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : bucketList.length === 0 ? (
          <EmptyState
            icon={Layers}
            title="No buckets configured"
            description="Use the preset templates above or the &quot;+ Add Custom Bucket&quot; button to create your company's balance buckets."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-line bg-muted/20 text-fg-subtle">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Bucket Name</th>
                  <th className="px-4 py-2.5 font-medium">Code</th>
                  <th className="px-4 py-2.5 font-medium">Type</th>
                  <th className="px-4 py-2.5 font-medium">Mapped Leave Types</th>
                  <th className="px-4 py-2.5 text-center font-medium">Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {bucketList.map((b) => {
                  const mapped = mappingsByBucket.get(b.id) || [];
                  return (
                    <tr key={b.id} className="transition-colors hover:bg-muted/40">
                      <td className="whitespace-nowrap px-4 py-3 font-medium text-fg">
                        {b.name}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-mono font-semibold text-fg-muted">
                        {b.code}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {b.is_unlimited ? (
                          <span className="inline-flex items-center gap-1 text-fg-subtle">
                            <InfinityIcon size={13} /> Unlimited
                          </span>
                        ) : (
                          <span className="text-fg-subtle">Standard Accrual</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {mapped.length === 0 ? (
                            <span className="italic text-fg-subtle">None mapped</span>
                          ) : (
                            mapped.map((m) => (
                              <span
                                key={m.id}
                                className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-fg-muted"
                              >
                                {m.leave_type_name}
                              </span>
                            ))
                          )}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-center">
                        <button
                          onClick={() =>
                            toggleBucketActive.mutate({ id: b.id, is_active: !b.is_active })
                          }
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium transition-colors ${
                            b.is_active
                              ? "bg-success/10 text-success hover:bg-success/20"
                              : "bg-muted text-fg-subtle hover:bg-muted/80"
                          }`}
                        >
                          {b.is_active ? (
                            <>
                              <CheckCircle2 size={11} /> Active
                            </>
                          ) : (
                            <>
                              <XCircle size={11} /> Inactive
                            </>
                          )}
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <button
                          className="rounded p-1 text-fg-subtle transition-colors hover:text-danger"
                          onClick={() => setConfirmDeleteBucketId(b.id)}
                          title="Archive bucket"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ─── Type-to-Bucket Mappings ─── */}
      <div className="card p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="card-title flex items-center gap-2">
              <LinkIcon size={16} className="text-accent" /> Type-to-Bucket Mappings
            </h3>
            <p className="text-xs text-fg-subtle">
              Links each leave request reason to its corresponding accounting ledger bucket.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {autoMappable.length > 0 && (
              <button
                className="btn-secondary btn-sm text-accent border-brand-500/30 hover:bg-brand-500/10"
                onClick={() => autoMapMutation.mutate(autoMappable)}
                disabled={autoMapMutation.isPending}
                title="Automatically map matching leave types and buckets"
              >
                <Sparkles size={14} className="text-accent" />
                {autoMapMutation.isPending ? "Auto-Mapping…" : `Auto-Map Matching (${autoMappable.length})`}
              </button>
            )}
            <button
              className="btn-primary btn-sm"
              onClick={() => setCreateMappingOpen(true)}
              disabled={unmappedTypes.length === 0 || bucketList.length === 0}
            >
              <Plus size={14} /> Map Leave Type
            </button>
          </div>
        </div>

        {mappings.isPending ? (
          <div className="space-y-3">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : mappingList.length === 0 ? (
          <EmptyState
            icon={LinkIcon}
            title="No mappings configured"
            description="Map your Leave Types (e.g. Sick Leave, Casual Leave) to a Balance Bucket."
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {mappingList.map((m) => (
              <div
                key={m.id}
                className="group flex items-center justify-between rounded-lg border border-line bg-panel p-3 shadow-xs transition-colors hover:border-line-strong hover:bg-surface"
              >
                <div className="min-w-0 flex-1 flex items-center gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-xs text-fg truncate">{m.leave_type_name}</span>
                      <span className="rounded bg-muted px-1 font-mono text-[10px] text-fg-subtle">
                        {m.leave_type_code}
                      </span>
                    </div>
                    <span className="text-[10px] text-fg-subtle block">Request Type</span>
                  </div>

                  <ArrowRight size={13} className="text-fg-subtle shrink-0 mx-1" />

                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-xs text-accent truncate">{m.bucket_name}</span>
                      <span className="rounded bg-brand-500/10 px-1 font-mono text-[10px] text-accent">
                        {m.bucket_code}
                      </span>
                    </div>
                    <span className="text-[10px] text-fg-subtle block">Ledger Balance</span>
                  </div>
                </div>
                <button
                  className="rounded p-1.5 text-fg-subtle transition-colors hover:text-danger hover:bg-danger/10 ml-2"
                  onClick={() => setConfirmDeleteMappingId(m.id)}
                  title="Remove mapping"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ─── Create Bucket Sheet ─── */}
      <Sheet
        open={createBucketOpen}
        onClose={() => setCreateBucketOpen(false)}
        title="Add Leave Bucket"
        description="A ledger balance bucket that holds leave days and tracks monthly continuity."
        footer={
          <>
            <button className="btn-secondary" onClick={() => setCreateBucketOpen(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => createBucket.mutate()}
              disabled={!bucketName.trim() || !bucketCode.trim() || createBucket.isPending}
            >
              {createBucket.isPending ? "Creating…" : "Create Bucket"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label text-xs mb-1.5 block">Select a standard template to pre-fill:</label>
            <div className="flex flex-wrap gap-1.5">
              {STANDARD_BUCKET_PRESETS.map((p) => {
                const isSelected = bucketCode.toUpperCase() === p.code;
                return (
                  <button
                    key={p.code}
                    type="button"
                    onClick={() => {
                      setBucketName(p.name);
                      setBucketCode(p.code);
                      setIsUnlimited(p.is_unlimited);
                    }}
                    className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                      isSelected
                        ? "border-brand-500 bg-brand-500/10 text-accent font-semibold"
                        : "border-line bg-panel text-fg-subtle hover:border-line-strong hover:text-fg"
                    }`}
                  >
                    {p.name} ({p.code})
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="label" htmlFor="nb-name">
              Bucket Name
            </label>
            <input
              id="nb-name"
              className="input"
              placeholder="e.g. Paid Leave or Sick Leave"
              value={bucketName}
              onChange={(e) => setBucketName(e.target.value)}
            />
          </div>

          <div>
            <label className="label" htmlFor="nb-code">
              Bucket Code
            </label>
            <input
              id="nb-code"
              className="input font-mono uppercase"
              placeholder="e.g. PL or SL"
              maxLength={10}
              value={bucketCode}
              onChange={(e) => setBucketCode(e.target.value)}
            />
          </div>

          <label className="flex items-center gap-2 text-xs text-fg cursor-pointer">
            <input
              type="checkbox"
              className="checkbox"
              checked={isUnlimited}
              onChange={(e) => setIsUnlimited(e.target.checked)}
            />
            <span>Unlimited balance bucket (e.g. for unpaid leave / LWP)</span>
          </label>
        </div>
      </Sheet>

      {/* ─── Create Mapping Sheet ─── */}
      <Sheet
        open={createMappingOpen}
        onClose={() => setCreateMappingOpen(false)}
        title="Map Leave Type to Bucket"
        description="Choose which leave type feeds into which ledger balance bucket."
        footer={
          <>
            <button className="btn-secondary" onClick={() => setCreateMappingOpen(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => createMapping.mutate()}
              disabled={!mappingTypeId || !mappingBucketId || createMapping.isPending}
            >
              {createMapping.isPending ? "Mapping…" : "Save Mapping"}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label" htmlFor="map-type">
              Leave Type
            </label>
            <select
              id="map-type"
              className="input"
              value={mappingTypeId}
              onChange={(e) => setMappingTypeId(e.target.value)}
            >
              <option value="">Select unmapped leave type…</option>
              {unmappedTypes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.code})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="map-bucket">
              Destination Bucket
            </label>
            <select
              id="map-bucket"
              className="input"
              value={mappingBucketId}
              onChange={(e) => setMappingBucketId(e.target.value)}
            >
              <option value="">Select balance bucket…</option>
              {bucketList.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.code})
                </option>
              ))}
            </select>
          </div>
        </div>
      </Sheet>

      {/* ─── Delete Bucket Confirmation ─── */}
      <ConfirmDialog
        open={!!confirmDeleteBucketId}
        onClose={() => setConfirmDeleteBucketId(null)}
        onConfirm={() => {
          if (confirmDeleteBucketId) deleteBucket.mutate(confirmDeleteBucketId);
        }}
        title="Archive Leave Bucket?"
        description="This bucket will no longer be available for new mappings. Historical ledger records will be preserved."
        confirmLabel="Archive Bucket"
      />

      {/* ─── Delete Mapping Confirmation ─── */}
      <ConfirmDialog
        open={!!confirmDeleteMappingId}
        onClose={() => setConfirmDeleteMappingId(null)}
        onConfirm={() => {
          if (confirmDeleteMappingId) deleteMapping.mutate(confirmDeleteMappingId);
        }}
        title="Remove Mapping?"
        description="The leave type will no longer point to this bucket. Applications will require a valid mapping."
        confirmLabel="Remove Mapping"
      />
    </div>
  );
}

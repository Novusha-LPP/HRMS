import { useState, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Shield,
  FileText,
  CalendarDays,
  Wallet,
  Plus,
  Trash2,
  Coins,
  RefreshCw,
  Clock,
  Umbrella,
  CalendarCheck2,
  PenLine,
  LogOut,
} from "lucide-react";
import type { LeaveType, UnifiedLeavePolicy } from "../api/leave";
import { leaveApi } from "../api/leave";
import { peopleApi } from "../api/people";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Segmented } from "../components/ui/Tabs";
import { Skeleton, Notice } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { usePeopleDirectory } from "../lib/usePeopleDirectory";
import { UnifiedLeavePoliciesTab } from "../components/leave/UnifiedLeavePoliciesTab";
import { LeavePolicySetsTab } from "../components/leave/LeavePolicySetsTab";
import { HolidayCalendars } from "../components/policy/HolidayCalendars";
import { LeaversSettings } from "../components/leave/LeaversSettings";

export type LeavePolicySection = "policies" | "policy-sets" | "types" | "holidays" | "operations" | "leavers";

export interface LeavePoliciesViewProps {
  standaloneHeader?: boolean;
  createSetOpen?: boolean;
  onOpenCreateSet?: () => void;
  onCloseCreateSet?: () => void;
  createPolicyOpen?: boolean;
  onOpenCreatePolicy?: () => void;
  onCloseCreatePolicy?: () => void;
}

export function LeavePoliciesView({
  standaloneHeader = true,
  createSetOpen,
  onOpenCreateSet,
  onCloseCreateSet,
  createPolicyOpen,
  onCloseCreatePolicy,
}: LeavePoliciesViewProps) {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const role = user?.role ?? "EMPLOYEE";
  const isHR = role === "HR" || role === "SUPER_ADMIN";

  const rawSection = (
    params.get("section") ||
    (params.get("tab") !== "leave" && params.get("tab") !== "attendance" ? params.get("tab") : null)
  ) as LeavePolicySection | null;

  const section: LeavePolicySection =
    rawSection && ["policies", "policy-sets", "types", "holidays", "operations", "leavers"].includes(rawSection)
      ? rawSection
      : "policies";

  const setSection = (next: LeavePolicySection) => {
    const nextParams = new URLSearchParams(params);
    if (!standaloneHeader) {
      nextParams.set("tab", "leave");
      if (next === "policies") {
        nextParams.delete("section");
      } else {
        nextParams.set("section", next);
      }
    } else {
      if (next === "policies") {
        nextParams.delete("tab");
      } else {
        nextParams.set("tab", next);
      }
    }
    setParams(nextParams, { replace: true });
  };

  useEffect(() => {
    if (createPolicyOpen && section !== "policies") {
      setSection("policies");
    }
  }, [createPolicyOpen, section]);

  const isOperations = section === "operations";
  const unified = useQuery<UnifiedLeavePolicy[]>({
    queryKey: ["unified-leave-policies"],
    queryFn: () => leaveApi.listUnifiedPolicies(),
    staleTime: 5 * 60 * 1000,
  });
  const types = useQuery<LeaveType[]>({
    queryKey: ["leave-types"],
    queryFn: () => leaveApi.listTypes(),
    enabled: isOperations || section === "types",
  });
  const employees = useQuery({
    queryKey: ["employees-picker"],
    queryFn: () => peopleApi.listAllEmployees(),
    enabled: isOperations,
  });
  const directory = usePeopleDirectory(isOperations);
  const employeeOptions = (employees.data ?? []).map((e) => ({
    id: e.id,
    label: directory.get(e.id) ?? e.employee_number,
  }));

  if (!isHR) {
    return (
      <div className="p-6">
        <Notice tone="warning" title="Access restricted">
          Only HR administrators and platform managers can access leave policy settings.
        </Notice>
      </div>
    );
  }

  return (
    <>
      {standaloneHeader && (
        <PageHeader
          title="Leave policies"
          description="Leave types, entitlement rules, holiday calendars and balance operations."
          actions={
            <div className="flex items-center gap-2">
              <Link to="/policy" className="btn-secondary btn-sm">
                <Clock size={14} /> Attendance policies
              </Link>
              <Link to="/leave" className="btn-secondary btn-sm">
                <Umbrella size={14} /> Leave requests
              </Link>
            </div>
          }
        />
      )}

      <div className="space-y-6">
        <Segmented
          value={section}
          onChange={(s) => setSection(s as LeavePolicySection)}
          items={[
            { value: "policies", label: "Leave Policies", icon: Shield },
            { value: "operations", label: "Grants & Operations", icon: Wallet },
            { value: "holidays", label: "Holiday Calendar", icon: CalendarDays },
            { value: "leavers", label: "Leavers & Rejoining", icon: LogOut },
            ...(["policy-sets", "types"].includes(section)
              ? [{ value: section, label: section === "types" ? "Leave Types (Advanced)" : "Policy Sets (Advanced)", icon: FileText }]
              : []),
          ]}
        />

        {section === "policies" && (
          <UnifiedLeavePoliciesTab
            policies={unified.data ?? []}
            loading={unified.isPending}
            createPolicyOpen={createPolicyOpen}
            onCloseCreatePolicy={onCloseCreatePolicy}
          />
        )}
        {section === "policy-sets" && (
          <LeavePolicySetsTab
            createSetOpen={createSetOpen}
            onOpenCreateSet={onOpenCreateSet}
            onCloseCreateSet={onCloseCreateSet}
          />
        )}
        {section === "types" && (
          <LeaveTypesCard types={types.data ?? []} loading={types.isPending} />
        )}
        {section === "holidays" && <HolidayCalendars />}
        {section === "leavers" && <LeaversSettings />}
        {section === "operations" && (
          <div className="grid gap-5 lg:grid-cols-2">
            <CompOffCard employees={employeeOptions} />
            <EncashmentCard
              employees={employeeOptions}
              types={(types.data ?? []).filter((t) => t.encashable)}
            />
            <AdjustBalanceCard
              employees={employeeOptions}
              types={(types.data ?? []).filter((t) => !t.is_comp_off)}
            />
            <AccrualCard />
            <YearEndCloseCard />
          </div>
        )}
      </div>
    </>
  );
}

export function LeavePoliciesPage() {
  return <LeavePoliciesView standaloneHeader={true} />;
}

function LeaveTypesCard({ types, loading }: { types: LeaveType[]; loading: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["leave-types"] });

  // Every edit carries the version on screen, so a change someone else saved first is refused
  // (409 STALE_VERSION) instead of silently overwritten.
  const versionOf = (id: string) => types.find((t) => t.id === id)?.version;
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<LeaveType> }) =>
      leaveApi.updateType(id, { ...body, version: versionOf(id) }),
    onSuccess: (saved) => {
      // The new version, at once: a second toggle before the list reloads must not look stale.
      qc.setQueryData<LeaveType[]>(["leave-types"], (old) => old?.map((t) => (t.id === saved.id ? saved : t)));
      void invalidate();
    },
    onError: (e) => toast.error("Couldn’t update leave type", errorMessage(e)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => leaveApi.removeType(id),
    onSuccess: () => { invalidate(); toast.success("Leave type removed"); },
    onError: (e) => toast.error("Couldn’t remove leave type", errorMessage(e)),
  });

  const [showArchived, setShowArchived] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingVersion, setEditingVersion] = useState<number>();
  const archived = useQuery({
    queryKey: ["leave-types", "archived"],
    queryFn: () => leaveApi.listArchivedTypes(),
    enabled: showArchived,
  });
  const restore = useMutation({
    mutationFn: (id: string) => leaveApi.restoreType(id),
    onSuccess: () => { invalidate(); toast.success("Leave type restored"); },
    onError: (e) => toast.error("Couldn’t restore leave type", errorMessage(e)),
  });
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [daysPerYear, setDaysPerYear] = useState("");
  const [isPaid, setIsPaid] = useState(true);
  const [requiresApproval, setRequiresApproval] = useState(true);

  const create = useMutation({
    mutationFn: () =>
      (editingId ? leaveApi.updateType(editingId, {
        version: editingVersion,
        name: name.trim(),
        code: code.trim(),
        days_per_year: Number(daysPerYear),
        is_paid: isPaid,
        requires_approval: requiresApproval,
      }) : leaveApi.createType({
        name: name.trim(), code: code.trim(), days_per_year: Number(daysPerYear),
        is_paid: isPaid, requires_approval: requiresApproval,
      })),
    onSuccess: () => {
      invalidate();
      setName("");
      setCode("");
      setDaysPerYear("");
      setIsPaid(true);
      setRequiresApproval(true);
      toast.success(editingId ? "Leave type updated" : "Leave type added");
      setEditingId(null);
    },
    onError: (e) => toast.error(editingId ? "Couldn’t update leave type" : "Couldn’t add leave type", errorMessage(e)),
  });

  const canCreate = name.trim() !== "" && code.trim() !== "" && daysPerYear !== "" && Number(daysPerYear) >= 0;

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1">Leave types</h3>
      <p className="mb-4 text-xs text-fg-subtle">
        Mark which types can be encashed, carry forward, or accrue automatically each month.
      </p>
      {loading ? (
        <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>
      ) : types.filter((t) => !t.is_comp_off).length === 0 ? (
        <p className="mb-4 text-xs text-fg-subtle">No leave types configured yet. Add one below.</p>
      ) : (
        <table className="mb-4 w-full text-[13px]">
          <thead>
            <tr className="text-left text-xs text-fg-subtle">
              <th className="pb-2 font-normal">Type</th>
              <th className="pb-2 font-normal text-center">Encashable</th>
              <th className="pb-2 font-normal text-center">Accrues monthly</th>
              <th className="pb-2 font-normal text-center">Carry forward</th>
              <th className="pb-2 font-normal text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {types.filter((t) => !t.is_comp_off).map((t) => (
              <tr key={t.id}>
                <td className="py-2">
                  <span className="inline-flex items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: t.color }} />
                    {t.name}
                  </span>
                </td>
                <td className="py-2 text-center">
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={t.encashable}
                    onChange={(e) => patch.mutate({ id: t.id, body: { encashable: e.target.checked } })}
                    aria-label={`${t.name} encashable`}
                  />
                </td>
                <td className="py-2 text-center">
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={t.accrual_enabled}
                    onChange={(e) => patch.mutate({ id: t.id, body: { accrual_enabled: e.target.checked } })}
                    aria-label={`${t.name} accrues monthly`}
                  />
                </td>
                <td className="py-2">
                  <div className="flex items-center justify-center gap-1.5">
                    <input
                      type="checkbox"
                      className="checkbox"
                      checked={t.carry_forward}
                      onChange={(e) =>
                        patch.mutate({
                          id: t.id,
                          body: {
                            carry_forward: e.target.checked,
                            ...(e.target.checked ? {} : { max_carry_forward_days: null }),
                          },
                        })
                      }
                      aria-label={`${t.name} carry forward`}
                    />
                    {t.carry_forward && (
                      <input
                        type="number"
                        min={0}
                        className="input w-16 px-2"
                        placeholder="cap"
                        defaultValue={t.max_carry_forward_days ?? ""}
                        onBlur={(e) =>
                          patch.mutate({
                            id: t.id,
                            body: { max_carry_forward_days: e.target.value === "" ? null : Number(e.target.value) },
                          })
                        }
                        aria-label={`${t.name} max carry-forward days`}
                        title="Max days to carry forward into next year (blank = uncapped)"
                      />
                    )}
                  </div>
                </td>
                <td className="py-2 text-right">
                  <button type="button" className="btn-secondary btn-sm mr-2"
                    onClick={() => {
                      setEditingVersion(t.version); setEditingId(t.id); setName(t.name); setCode(t.code);
                      setDaysPerYear(String(t.days_per_year)); setIsPaid(t.is_paid);
                      setRequiresApproval(t.requires_approval);
                    }}>
                    <PenLine size={14} /> Edit
                  </button>
                  <button type="button" className="btn-secondary btn-sm" disabled={remove.isPending || editingId === t.id}
                    aria-label={`Remove ${t.name}`}
                    onClick={() => {
                      if (window.confirm(`Remove ${t.name}? Past leave requests and balances will be preserved. New requests will no longer be allowed.`)) remove.mutate(t.id);
                    }}>
                    <Trash2 size={14} /> Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editingId && <p className="mb-2 text-sm font-medium">Editing leave type</p>}
      <form
        className="flex flex-wrap items-end gap-2 border-t border-line pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (canCreate) create.mutate();
        }}
      >
        <div>
          <label className="label" htmlFor="lt-name">Name</label>
          <input
            id="lt-name"
            className="input"
            placeholder="e.g. Privilege Leave"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="lt-code">Code</label>
          <input
            id="lt-code"
            className="input w-20"
            placeholder="PL"
            maxLength={10}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="lt-days">Days / year</label>
          <input
            id="lt-days"
            type="number"
            min={0}
            step="0.5"
            className="input w-24"
            placeholder="18"
            value={daysPerYear}
            onChange={(e) => setDaysPerYear(e.target.value)}
          />
        </div>
        <label className="mb-2 flex items-center gap-1.5 text-xs text-fg-subtle">
          <input type="checkbox" className="checkbox" checked={isPaid} onChange={(e) => setIsPaid(e.target.checked)} />
          Paid
        </label>
        <label className="mb-2 flex items-center gap-1.5 text-xs text-fg-subtle">
          <input
            type="checkbox"
            className="checkbox"
            checked={requiresApproval}
            onChange={(e) => setRequiresApproval(e.target.checked)}
          />
          Requires approval
        </label>
        <button className="btn-secondary btn-sm" type="submit" disabled={!canCreate || create.isPending}>
          {editingId ? <PenLine size={14} /> : <Plus size={14} />}
          {editingId ? "Save changes" : "Add leave type"}
        </button>
        {editingId && <button type="button" className="btn-secondary btn-sm" disabled={create.isPending}
          onClick={() => {
            setEditingId(null); setName(""); setCode(""); setDaysPerYear("");
            setIsPaid(true); setRequiresApproval(true);
          }}>Cancel edit</button>}
      </form>
      <div className="mt-4 border-t border-line pt-4">
        <button type="button" className="btn-secondary btn-sm" aria-expanded={showArchived}
          onClick={() => setShowArchived((v) => !v)}>
          {showArchived ? "Hide archived leave types" : "Archived leave types"}
        </button>
        {showArchived && (
          <div className="mt-3 space-y-2">
            {archived.isPending ? <Skeleton className="h-9" /> : archived.isError ? (
              <Notice tone="warning" title="Couldn’t load archived leave types">
                <button type="button" className="link" onClick={() => archived.refetch()}>Try again</button>
              </Notice>
            ) : !archived.data?.length ? <p className="text-xs text-fg-subtle">No archived leave types.</p> : (
              archived.data.map((t) => (
                <div key={t.id} className="flex items-center justify-between gap-3 rounded border border-line p-3">
                  <span className="text-sm">{t.name} ({t.code}) · {t.days_per_year} days/year</span>
                  <button type="button" className="btn-secondary btn-sm" disabled={restore.isPending}
                    onClick={() => restore.mutate(t.id)}><RefreshCw size={14} /> Restore</button>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function CompOffCard({ employees }: { employees: { id: string; label: string }[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [empId, setEmpId] = useState("");
  const [workDate, setWorkDate] = useState("");
  const [days, setDays] = useState("1");
  const [notes, setNotes] = useState("");

  const grant = useMutation({
    mutationFn: () =>
      leaveApi.grantCompOff({
        employment_id: empId,
        work_date: workDate,
        days_granted: Number(days),
        notes: notes.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-balances"] });
      toast.success("Comp-off granted");
      setWorkDate("");
      setDays("1");
      setNotes("");
    },
    onError: (e) => toast.error("Couldn’t grant comp-off", errorMessage(e)),
  });

  const valid = !!empId && !!workDate && Number(days) > 0;

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1 flex items-center gap-2">
        <Wallet size={15} /> Grant comp-off
      </h3>
      <p className="mb-4 text-xs text-fg-subtle">
        Credits the employee’s Comp Off balance for a day worked outside their normal schedule.
      </p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) grant.mutate();
        }}
      >
        <div>
          <label className="label" htmlFor="co-emp">Employee</label>
          <select id="co-emp" className="input" value={empId} onChange={(e) => setEmpId(e.target.value)}>
            <option value="">Select employee…</option>
            {employees.map((e) => (
              <option key={e.id} value={e.id}>{e.label}</option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="co-date">Work date</label>
            <input id="co-date" type="date" className="input" value={workDate} onChange={(e) => setWorkDate(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="co-days">Days</label>
            <input
              id="co-days"
              type="number"
              min="0.5"
              step="0.5"
              className="input"
              value={days}
              onChange={(e) => setDays(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="co-notes">
            Notes <span className="font-normal text-fg-subtle">(optional)</span>
          </label>
          <input
            id="co-notes"
            className="input"
            placeholder="e.g. Worked the Sunday release"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
        <button className="btn-primary btn-sm" type="submit" disabled={!valid || grant.isPending}>
          {grant.isPending ? "Granting…" : "Grant comp-off"}
        </button>
      </form>
    </div>
  );
}

function EncashmentCard({
  employees,
  types,
}: {
  employees: { id: string; label: string }[];
  types: LeaveType[];
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [empId, setEmpId] = useState("");
  const [typeId, setTypeId] = useState("");
  const [days, setDays] = useState("");
  const [notes, setNotes] = useState("");

  const encash = useMutation({
    mutationFn: () =>
      leaveApi.encash({
        employment_id: empId,
        leave_type_id: typeId,
        days: Number(days),
        notes: notes.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leave-balances"] });
      toast.success("Leave encashed");
      setDays("");
      setNotes("");
    },
    onError: (e) => toast.error("Couldn’t encash leave", errorMessage(e)),
  });

  const valid = !!empId && !!typeId && Number(days) > 0;

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1 flex items-center gap-2">
        <Coins size={15} /> Encash leave
      </h3>
      <p className="mb-4 text-xs text-fg-subtle">
        Converts unused balance to a payout record for payroll to process externally.
      </p>
      {types.length === 0 ? (
        <Notice title="No encashable leave types">Mark a type “Encashable” in the Leave types card first.</Notice>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) encash.mutate();
          }}
        >
          <div>
            <label className="label" htmlFor="en-emp">Employee</label>
            <select id="en-emp" className="input" value={empId} onChange={(e) => setEmpId(e.target.value)}>
              <option value="">Select employee…</option>
              {employees.map((e) => (
                <option key={e.id} value={e.id}>{e.label}</option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="en-type">Leave type</label>
              <select id="en-type" className="input" value={typeId} onChange={(e) => setTypeId(e.target.value)}>
                <option value="">Select…</option>
                {types.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="en-days">Days</label>
              <input
                id="en-days"
                type="number"
                min="0.5"
                step="0.5"
                className="input"
                value={days}
                onChange={(e) => setDays(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="en-notes">
              Notes <span className="font-normal text-fg-subtle">(optional)</span>
            </label>
            <input
              id="en-notes"
              className="input"
              placeholder="e.g. Year-end encashment"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <button className="btn-primary btn-sm" type="submit" disabled={!valid || encash.isPending}>
            {encash.isPending ? "Processing…" : "Encash"}
          </button>
        </form>
      )}
    </div>
  );
}

function AdjustBalanceCard({
  employees,
  types,
}: {
  employees: { id: string; label: string }[];
  types: LeaveType[];
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [empId, setEmpId] = useState("");
  const [typeId, setTypeId] = useState("");
  const [kind, setKind] = useState<"OPENING" | "ADJUSTMENT">("OPENING");
  const [quantity, setQuantity] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [reason, setReason] = useState("");

  const adjust = useMutation({
    mutationFn: () =>
      leaveApi.adjustBalance({
        employment_id: empId,
        leave_type_id: typeId,
        quantity: Number(quantity),
        effective_date: effectiveDate || undefined,
        reason: reason.trim(),
        kind,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["leave-balances"] });
      toast.success("Balance updated", `New balance: ${res.new_balance} days`);
      setQuantity("");
      setEffectiveDate("");
      setReason("");
    },
    onError: (e) => toast.error("Couldn’t adjust balance", errorMessage(e)),
  });

  const valid = !!empId && !!typeId && Number(quantity) !== 0 && reason.trim().length > 0;

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1 flex items-center gap-2">
        <PenLine size={15} /> Adjust balance
      </h3>
      <p className="mb-4 text-xs text-fg-subtle">
        One-off credit or debit — seed an opening balance carried over from a previous system, or
        correct a mistake. Not for routine accrual.
      </p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) adjust.mutate();
        }}
      >
        <div>
          <label className="label" htmlFor="adj-emp">Employee</label>
          <select id="adj-emp" className="input" value={empId} onChange={(e) => setEmpId(e.target.value)}>
            <option value="">Select employee…</option>
            {employees.map((e) => (
              <option key={e.id} value={e.id}>{e.label}</option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="adj-type">Leave type</label>
            <select id="adj-type" className="input" value={typeId} onChange={(e) => setTypeId(e.target.value)}>
              <option value="">Select…</option>
              {types.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="adj-kind">Reason type</label>
            <select
              id="adj-kind"
              className="input"
              value={kind}
              onChange={(e) => setKind(e.target.value as "OPENING" | "ADJUSTMENT")}
            >
              <option value="OPENING">Opening balance</option>
              <option value="ADJUSTMENT">Correction</option>
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="adj-days">
              Days <span className="font-normal text-fg-subtle">(negative to remove)</span>
            </label>
            <input
              id="adj-days"
              type="number"
              step="0.5"
              className="input"
              placeholder="100"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="adj-date">
              Effective date <span className="font-normal text-fg-subtle">(optional)</span>
            </label>
            <input
              id="adj-date"
              type="date"
              className="input"
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="adj-reason">Reason</label>
          <input
            id="adj-reason"
            className="input"
            placeholder="e.g. Carried over from previous HR system"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>
        <button className="btn-primary btn-sm" type="submit" disabled={!valid || adjust.isPending}>
          {adjust.isPending ? "Saving…" : "Apply adjustment"}
        </button>
      </form>
    </div>
  );
}

function AccrualCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const currentPeriod = format(new Date(), "yyyy-MM");
  const [period, setPeriod] = useState(currentPeriod);

  const run = useMutation({
    mutationFn: () => leaveApi.runAccrual(period),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["leave-balances"] });
      toast.success(
        res.balances_credited > 0 ? `Accrual run for ${res.period}` : `Nothing to accrue for ${res.period}`,
        res.balances_credited > 0
          ? `${res.balances_credited} balances credited, ${res.days_credited_total} days total.`
          : "Already run, or no types have accrual enabled.",
      );
    },
    onError: (e) => toast.error("Accrual run failed", errorMessage(e)),
  });

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1 flex items-center gap-2">
        <RefreshCw size={15} /> Monthly accrual
      </h3>
      <p className="mb-4 text-xs text-fg-subtle">
        Credits days_per_year ÷ 12 to every active employee for types marked “Accrues monthly.” Safe to re-run — a
        period is only ever credited once.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="label" htmlFor="acc-period">Period</label>
          <input
            id="acc-period"
            type="month"
            className="input"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
        </div>
        <button className="btn-primary btn-sm" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Running…" : "Run accrual"}
        </button>
      </div>
    </div>
  );
}

function YearEndCloseCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const currentFy = new Date().getFullYear();
  const [fyYear, setFyYear] = useState(currentFy);

  const run = useMutation({
    mutationFn: () => leaveApi.yearEndClose(fyYear),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["leave-balances"] });
      toast.success(
        `FY${res.fy_year} closed`,
        `${res.buckets_closed} balance(s) closed, ${res.days_lapsed} day(s) lapsed. The rest carried forward.`,
      );
    },
    onError: (e) => toast.error("Year-end close failed", errorMessage(e)),
  });

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1 flex items-center gap-2">
        <CalendarCheck2 size={15} /> Year-end close
      </h3>
      <p className="mb-4 text-xs text-fg-subtle">
        Caps each employee's closing balance at their leave type's carry-forward limit — the
        excess lapses, the rest becomes next year's opening balance. Uses each legal entity's own
        financial year (April by default). Safe to re-run — a balance is only ever closed once
        per year.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="label" htmlFor="yec-fy">Financial year</label>
          <input
            id="yec-fy"
            type="number"
            className="input w-28"
            value={fyYear}
            onChange={(e) => setFyYear(Number(e.target.value))}
          />
        </div>
        <button className="btn-primary btn-sm" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Closing…" : "Close year"}
        </button>
      </div>
    </div>
  );
}

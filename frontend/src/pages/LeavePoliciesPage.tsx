import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Shield,
  Layers,
  FileText,
  CalendarDays,
  Wallet,
  Plus,
  Trash2,
  Coins,
  RefreshCw,
  Clock,
  Umbrella,
} from "lucide-react";
import type { LeaveType, Holiday } from "../api/leave";
import { leaveApi } from "../api/leave";
import { peopleApi } from "../api/people";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/ui/PageHeader";
import { Segmented } from "../components/ui/Tabs";
import { Skeleton, Notice } from "../components/ui/Feedback";
import { useToast, errorMessage } from "../components/ui/Toast";
import { usePeopleDirectory } from "../lib/usePeopleDirectory";
import { LeaveBucketsTab } from "../components/leave/LeaveBucketsTab";
import { LeavePolicySetsTab } from "../components/leave/LeavePolicySetsTab";

export type LeavePolicySection = "policy-sets" | "buckets" | "types" | "holidays" | "operations";

export interface LeavePoliciesViewProps {
  standaloneHeader?: boolean;
  createSetOpen?: boolean;
  onOpenCreateSet?: () => void;
  onCloseCreateSet?: () => void;
}

export function LeavePoliciesView({
  standaloneHeader = true,
  createSetOpen,
  onOpenCreateSet,
  onCloseCreateSet,
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
    rawSection && ["policy-sets", "buckets", "types", "holidays", "operations"].includes(rawSection)
      ? rawSection
      : "policy-sets";

  const setSection = (next: LeavePolicySection) => {
    const nextParams = new URLSearchParams(params);
    if (!standaloneHeader) {
      nextParams.set("tab", "leave");
      if (next === "policy-sets") {
        nextParams.delete("section");
      } else {
        nextParams.set("section", next);
      }
    } else {
      if (next === "policy-sets") {
        nextParams.delete("tab");
      } else {
        nextParams.set("tab", next);
      }
    }
    setParams(nextParams, { replace: true });
  };

  const year = new Date().getFullYear();
  const types = useQuery<LeaveType[]>({ queryKey: ["leave-types"], queryFn: () => leaveApi.listTypes() });
  const holidays = useQuery<Holiday[]>({ queryKey: ["holidays", year], queryFn: () => leaveApi.listHolidays(year) });
  const employees = useQuery({ queryKey: ["employees-picker"], queryFn: () => peopleApi.listAllEmployees() });
  const directory = usePeopleDirectory(true);
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
          description="Policy sets, entitlement rules, balance buckets, holiday calendars and balance operations."
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
            { value: "policy-sets", label: "Policy Sets & Rules", icon: Shield },
            { value: "buckets", label: "Buckets & Mappings", icon: Layers },
            { value: "types", label: "Leave Types", icon: FileText },
            { value: "holidays", label: "Holiday Calendar", icon: CalendarDays },
            { value: "operations", label: "Grants & Operations", icon: Wallet },
          ]}
        />

        {section === "policy-sets" && (
          <LeavePolicySetsTab
            createSetOpen={createSetOpen}
            onOpenCreateSet={onOpenCreateSet}
            onCloseCreateSet={onCloseCreateSet}
          />
        )}
        {section === "buckets" && <LeaveBucketsTab />}
        {section === "types" && (
          <LeaveTypesCard types={types.data ?? []} loading={types.isPending} />
        )}
        {section === "holidays" && (
          <HolidaysCard holidays={holidays.data ?? []} loading={holidays.isPending} year={year} />
        )}
        {section === "operations" && (
          <div className="grid gap-5 lg:grid-cols-2">
            <CompOffCard employees={employeeOptions} />
            <EncashmentCard
              employees={employeeOptions}
              types={(types.data ?? []).filter((t) => t.encashable)}
            />
            <div className="lg:col-span-2">
              <AccrualCard />
            </div>
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
  const toggle = useMutation({
    mutationFn: ({ id, field, value }: { id: string; field: "encashable" | "accrual_enabled"; value: boolean }) =>
      leaveApi.updateType(id, { [field]: value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leave-types"] }),
    onError: (e) => toast.error("Couldn’t update leave type", errorMessage(e)),
  });

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1">Leave types</h3>
      <p className="mb-4 text-xs text-fg-subtle">Mark which types can be encashed or accrue automatically each month.</p>
      {loading ? (
        <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>
      ) : types.filter((t) => !t.is_comp_off).length === 0 ? (
        <p className="text-xs text-fg-subtle">No leave types configured yet.</p>
      ) : (
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-xs text-fg-subtle">
              <th className="pb-2 font-normal">Type</th>
              <th className="pb-2 font-normal text-center">Encashable</th>
              <th className="pb-2 font-normal text-center">Accrues monthly</th>
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
                    onChange={(e) => toggle.mutate({ id: t.id, field: "encashable", value: e.target.checked })}
                    aria-label={`${t.name} encashable`}
                  />
                </td>
                <td className="py-2 text-center">
                  <input
                    type="checkbox"
                    className="checkbox"
                    checked={t.accrual_enabled}
                    onChange={(e) => toggle.mutate({ id: t.id, field: "accrual_enabled", value: e.target.checked })}
                    aria-label={`${t.name} accrues monthly`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function HolidaysCard({ holidays, loading, year }: { holidays: Holiday[]; loading: boolean; year: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const [optional, setOptional] = useState(false);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["holidays", year] });
  const create = useMutation({
    mutationFn: () => leaveApi.createHoliday({ holiday_date: date, name: name.trim(), is_optional: optional }),
    onSuccess: () => {
      invalidate();
      setDate("");
      setName("");
      setOptional(false);
      toast.success("Holiday added");
    },
    onError: (e) => toast.error("Couldn’t add holiday", errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => leaveApi.deleteHoliday(id),
    onSuccess: () => {
      invalidate();
      toast.success("Holiday removed");
    },
    onError: (e) => toast.error("Couldn’t remove holiday", errorMessage(e)),
  });

  return (
    <div className="card p-5">
      <h3 className="card-title mb-1 flex items-center gap-2">
        <CalendarDays size={15} /> Holiday calendar · {year}
      </h3>
      <p className="mb-4 text-xs text-fg-subtle">
        Excluded from working-day counts on leave requests and shown as Holiday in Daily Analysis.
      </p>
      {loading ? (
        <div className="space-y-2">{[0, 1].map((i) => <Skeleton key={i} className="h-9" />)}</div>
      ) : holidays.length === 0 ? (
        <p className="mb-4 text-xs text-fg-subtle">No holidays added for {year} yet.</p>
      ) : (
        <ul className="mb-4 divide-y divide-line">
          {holidays.map((h) => (
            <li key={h.id} className="flex items-center justify-between gap-3 py-2 text-[13px]">
              <span className="text-fg-subtle tabular-nums">{format(new Date(h.holiday_date), "d MMM yyyy")}</span>
              <span className="flex-1 truncate text-fg">
                {h.name}
                {h.is_optional && <span className="ml-1.5 text-xs text-fg-subtle">(optional)</span>}
              </span>
              <button
                className="text-fg-subtle transition-colors hover:text-danger"
                onClick={() => remove.mutate(h.id)}
                aria-label={`Remove ${h.name}`}
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (date && name.trim()) create.mutate();
        }}
      >
        <div>
          <label className="label" htmlFor="hol-date">Date</label>
          <input id="hol-date" type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        <div className="min-w-0 flex-1">
          <label className="label" htmlFor="hol-name">Name</label>
          <input
            id="hol-name"
            className="input"
            placeholder="e.g. Independence Day"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <label className="mb-2 flex items-center gap-1.5 text-xs text-fg-subtle">
          <input
            type="checkbox"
            className="checkbox"
            checked={optional}
            onChange={(e) => setOptional(e.target.checked)}
          />{" "}
          Optional
        </label>
        <button className="btn-secondary btn-sm" type="submit" disabled={!date || !name.trim() || create.isPending}>
          <Plus size={14} /> Add
        </button>
      </form>
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

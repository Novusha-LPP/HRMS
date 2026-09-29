import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  BookOpen,
  History,
  Lock,
  ArrowRight,
  Layers,
} from "lucide-react";
import {
  leaveApi,
  type LeaveBalanceBucket,
  type LeaveMonthlyLedger,
  type LeaveBalanceTransaction,
} from "../../api/leave";
import { peopleApi } from "../../api/people";
import { usePeopleDirectory } from "../../lib/usePeopleDirectory";
import { EmptyState, Skeleton } from "../ui/Feedback";
import { Segmented } from "../ui/Tabs";

const MONTH_NAMES = [
  "",
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

const TX_BADGE_STYLE: Record<string, { label: string; className: string }> = {
  HOLD: { label: "Hold (Pending)", className: "bg-warning/10 text-warning border-warning/20" },
  RELEASE: { label: "Released", className: "bg-info/10 text-info border-info/20" },
  LEAVE_TAKEN: { label: "Leave Taken", className: "bg-danger/10 text-danger border-danger/20" },
  LEAVE_REVERSED: { label: "Reversed", className: "bg-plum/10 text-plum border-plum/20" },
  ACCRUAL: { label: "Accrual Credit", className: "bg-success/10 text-success border-success/20" },
  GRANT: { label: "Grant Added", className: "bg-success/10 text-success border-success/20" },
  LAPSE: { label: "Lapsed", className: "bg-muted text-fg-subtle border-line" },
  ENCASHMENT: { label: "Encashed", className: "bg-info/10 text-info border-info/20" },
  ADJUSTMENT: { label: "Adjustment", className: "bg-warning/10 text-warning border-warning/20" },
  YEAR_END_CLOSE: { label: "Year-End Close", className: "bg-plum/10 text-plum border-plum/20" },
};

export function LeaveLedgerView({
  currentEmploymentId,
  isPrivileged,
}: {
  currentEmploymentId: string | null;
  isPrivileged: boolean;
}) {
  const currentYear = new Date().getFullYear();
  const [selectedEmpId, setSelectedEmpId] = useState<string>(currentEmploymentId || "");
  const [selectedFy, setSelectedFy] = useState<number>(currentYear);
  const [selectedBucketId, setSelectedBucketId] = useState<string>("");
  const [viewMode, setViewMode] = useState<"ledger" | "audit">("ledger");

  const directory = usePeopleDirectory(isPrivileged);
  const employees = useQuery({
    queryKey: ["employees-picker"],
    queryFn: () => peopleApi.listAllEmployees(),
    enabled: isPrivileged,
  });

  const buckets = useQuery<LeaveBalanceBucket[]>({
    queryKey: ["leave-buckets"],
    queryFn: () => leaveApi.listBuckets(),
  });

  const activeEmpId = selectedEmpId || currentEmploymentId || "";

  const ledger = useQuery<LeaveMonthlyLedger[]>({
    queryKey: ["leave-ledger", activeEmpId, selectedFy, selectedBucketId],
    queryFn: () =>
      leaveApi.getLedger(activeEmpId, {
        fy_year: selectedFy,
        bucket_id: selectedBucketId || undefined,
      }),
    enabled: !!activeEmpId,
  });

  const transactions = useQuery<LeaveBalanceTransaction[]>({
    queryKey: ["leave-transactions", activeEmpId, selectedBucketId],
    queryFn: () =>
      leaveApi.getTransactions(activeEmpId, {
        bucket_id: selectedBucketId || undefined,
      }),
    enabled: !!activeEmpId && viewMode === "audit",
  });

  const ledgerRows = ledger.data ?? [];
  const txRows = transactions.data ?? [];

  // Group ledger rows by bucket
  const bucketMap = new Map<string, LeaveMonthlyLedger[]>();
  for (const row of ledgerRows) {
    const list = bucketMap.get(row.bucket_id) || [];
    list.push(row);
    bucketMap.set(row.bucket_id, list);
  }

  return (
    <div className="space-y-6">
      {/* Filter and selector toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-panel p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          {isPrivileged && (
            <div className="min-w-[220px]">
              <label htmlFor="ledger-employee-select" className="label text-xs">Employee</label>
              <select
                id="ledger-employee-select"
                className="input text-xs"
                value={activeEmpId}
                onChange={(e) => setSelectedEmpId(e.target.value)}
              >
                {!currentEmploymentId && <option value="">Select an employee…</option>}
                {(employees.data ?? []).map((e) => (
                  <option key={e.id} value={e.id}>
                    {directory.get(e.id) ?? e.employee_number}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label htmlFor="ledger-bucket-select" className="label text-xs">Balance Bucket</label>
            <select
              id="ledger-bucket-select"
              className="input text-xs"
              value={selectedBucketId}
              onChange={(e) => setSelectedBucketId(e.target.value)}
            >
              <option value="">All Buckets</option>
              {(buckets.data ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.code})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="ledger-fy-select" className="label text-xs">Financial Year</label>
            <select
              id="ledger-fy-select"
              className="input text-xs"
              value={selectedFy}
              onChange={(e) => setSelectedFy(Number(e.target.value))}
            >
              <option value={currentYear - 1}>FY {currentYear - 1}–{currentYear}</option>
              <option value={currentYear}>FY {currentYear}–{currentYear + 1}</option>
              <option value={currentYear + 1}>FY {currentYear + 1}–{currentYear + 2}</option>
            </select>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Segmented
            value={viewMode}
            onChange={(v) => setViewMode(v)}
            items={[
              { value: "ledger", label: "Monthly Ledger", icon: BookOpen },
              { value: "audit", label: "Audit Journal", icon: History },
            ]}
          />
        </div>
      </div>

      {!activeEmpId ? (
        <div className="card p-10">
          <EmptyState
            icon={BookOpen}
            title="Select an employee"
            description="Choose an employee from the dropdown above to inspect their monthly leave ledger."
          />
        </div>
      ) : viewMode === "ledger" ? (
        /* ── Monthly Ledger View ── */
        ledger.isPending ? (
          <div className="space-y-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        ) : ledgerRows.length === 0 ? (
          <div className="card p-10">
            <EmptyState
              icon={BookOpen}
              title="No ledger entries for this period"
              description="Monthly ledger balances are created automatically when employees apply for leave or when monthly accruals run."
            />
          </div>
        ) : (
          <div className="space-y-6">
            {Array.from(bucketMap.entries()).map(([bId, rows]) => {
              const latest = rows[rows.length - 1];
              return (
                <div key={bId} className="card overflow-hidden">
                  <div className="flex flex-wrap items-center justify-between border-b border-line bg-muted/30 px-5 py-4">
                    <div>
                      <h3 className="flex items-center gap-2 text-base font-semibold text-fg">
                        <Layers size={17} className="text-accent" />
                        {latest.bucket_name}
                        <span className="font-mono text-xs font-normal text-fg-subtle">
                          ({latest.bucket_code})
                        </span>
                      </h3>
                      <p className="text-xs text-fg-subtle">
                        Financial Year {selectedFy}–{selectedFy + 1} Ledger Sequence
                      </p>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <span className="block text-[11px] text-fg-subtle">Closing Balance</span>
                        <span className="font-mono text-base font-semibold tabular-nums text-fg">
                          {latest.closing}
                        </span>
                      </div>
                      <div className="h-8 w-px bg-line" />
                      <div className="text-right">
                        <span className="block text-[11px] text-fg-subtle">Available (Net)</span>
                        <span className="font-mono text-base font-semibold tabular-nums text-success">
                          {latest.available}
                        </span>
                      </div>
                      {latest.held > 0 && (
                        <>
                          <div className="h-8 w-px bg-line" />
                          <div className="text-right">
                            <span className="flex items-center gap-1 text-[11px] text-warning">
                              <Lock size={11} /> Held
                            </span>
                            <span className="font-mono text-base font-semibold tabular-nums text-warning">
                              {latest.held}
                            </span>
                          </div>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="border-b border-line bg-muted/20 text-fg-subtle">
                        <tr>
                          <th className="px-4 py-3 font-medium">Month</th>
                          <th className="px-4 py-3 text-right font-medium">Opening</th>
                          <th className="px-4 py-3 text-right font-medium text-success">+ Accrued</th>
                          <th className="px-4 py-3 text-right font-medium text-success">+ Granted</th>
                          <th className="px-4 py-3 text-right font-medium text-warning">Held</th>
                          <th className="px-4 py-3 text-right font-medium text-danger">- Taken</th>
                          <th className="px-4 py-3 text-right font-medium text-fg-subtle">- Lapsed</th>
                          <th className="px-4 py-3 text-right font-medium text-fg-subtle">- Encashed</th>
                          <th className="px-4 py-3 text-right font-medium">Adj</th>
                          <th className="px-4 py-3 text-right font-medium font-semibold text-fg">
                            Closing
                          </th>
                          <th className="px-4 py-3 text-right font-medium font-semibold text-accent">
                            Available
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line tabular-nums">
                        {rows.map((row, idx) => {
                          const prev = idx > 0 ? rows[idx - 1] : null;
                          const hasContinuity = !prev || prev.closing === row.opening;
                          return (
                            <tr key={row.id} className="transition-colors hover:bg-muted/40">
                              <td className="whitespace-nowrap px-4 py-3 font-medium text-fg">
                                {MONTH_NAMES[row.calendar_month]} {row.calendar_year}
                              </td>
                              <td className="px-4 py-3 text-right font-mono">
                                <span
                                  className={
                                    hasContinuity
                                      ? "text-fg"
                                      : "rounded bg-danger/10 px-1 text-danger font-bold"
                                  }
                                  title={hasContinuity ? "Continuous" : "Continuity Discrepancy"}
                                >
                                  {row.opening}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-success">
                                {row.accrued > 0 ? `+${row.accrued}` : "0"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-success">
                                {row.granted > 0 ? `+${row.granted}` : "0"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-warning">
                                {row.held > 0 ? `${row.held}` : "0"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-danger">
                                {row.taken > 0 ? `-${row.taken}` : "0"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-fg-subtle">
                                {row.lapsed > 0 ? `-${row.lapsed}` : "0"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-fg-subtle">
                                {row.encashed > 0 ? `-${row.encashed}` : "0"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono text-fg-subtle">
                                {row.adjustment !== 0
                                  ? row.adjustment > 0
                                    ? `+${row.adjustment}`
                                    : row.adjustment
                                  : "0"}
                              </td>
                              <td className="px-4 py-3 text-right font-mono font-semibold text-fg">
                                {row.closing}
                              </td>
                              <td className="px-4 py-3 text-right font-mono font-semibold text-accent">
                                {row.available}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : (
        /* ── Audit Transaction Journal ── */
        transactions.isPending ? (
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : txRows.length === 0 ? (
          <div className="card p-10">
            <EmptyState
              icon={History}
              title="No balance transactions recorded yet"
              description="Every leave application hold, approval, reversal, and accrual credit is logged as an immutable transaction."
            />
          </div>
        ) : (
          <div className="card overflow-hidden">
            <div className="border-b border-line bg-muted/30 px-5 py-4">
              <h3 className="text-sm font-semibold text-fg">Immutable Leave Transaction Log</h3>
              <p className="text-xs text-fg-subtle">
                Complete audit trail of all balance adjustments, holds, and movements.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-line bg-muted/20 text-fg-subtle">
                  <tr>
                    <th className="px-4 py-3 font-medium">Effective Date</th>
                    <th className="px-4 py-3 font-medium">Bucket</th>
                    <th className="px-4 py-3 font-medium">Type</th>
                    <th className="px-4 py-3 text-right font-medium">Quantity</th>
                    <th className="px-4 py-3 text-center font-medium">Balance Transition</th>
                    <th className="px-4 py-3 font-medium">Reason / Reference</th>
                    <th className="px-4 py-3 font-medium">Recorded At</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line tabular-nums">
                  {txRows.map((tx) => {
                    const badge = TX_BADGE_STYLE[tx.transaction_type] || {
                      label: tx.transaction_type,
                      className: "bg-muted text-fg-subtle border-line",
                    };
                    const isCredit = [
                      "ACCRUAL",
                      "GRANT",
                      "LEAVE_REVERSED",
                      "RELEASE",
                    ].includes(tx.transaction_type);
                    return (
                      <tr key={tx.id} className="transition-colors hover:bg-muted/40">
                        <td className="whitespace-nowrap px-4 py-3 font-medium text-fg">
                          {format(new Date(tx.effective_date), "dd MMM yyyy")}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 font-medium text-fg">
                          {tx.bucket_name}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <span
                            className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium ${badge.className}`}
                          >
                            {badge.label}
                          </span>
                        </td>
                        <td
                          className={`px-4 py-3 text-right font-mono font-semibold ${
                            isCredit ? "text-success" : "text-danger"
                          }`}
                        >
                          {isCredit ? `+${tx.quantity}` : `-${tx.quantity}`}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-center font-mono text-fg-subtle">
                          <span>{tx.previous_balance}</span>
                          <ArrowRight size={12} className="inline mx-1.5 opacity-60" />
                          <span className="font-semibold text-fg">{tx.new_balance}</span>
                        </td>
                        <td className="max-w-[260px] truncate px-4 py-3 text-fg-subtle">
                          {tx.reason || (tx.reference_type ? `${tx.reference_type}` : "—")}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-fg-subtle">
                          {format(new Date(tx.recorded_at), "dd MMM HH:mm")}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}
    </div>
  );
}

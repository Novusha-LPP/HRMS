import { useState } from "react";
import {
  Dialog,
} from "../ui/Overlay";
import {
  Info,
  Clock,
  Layers,
  ArrowRight,
  Shield,
  FileText,
  Building2,
  CheckCircle2,
  HelpCircle,
  Sparkles,
} from "lucide-react";
import { Segmented } from "../ui/Tabs";

interface PolicyExplainerModalProps {
  open: boolean;
  onClose: () => void;
  initialTab?: "leave" | "attendance" | "examples";
}

export function PolicyExplainerModal({
  open,
  onClose,
  initialTab = "leave",
}: PolicyExplainerModalProps) {
  const [tab, setTab] = useState<"leave" | "attendance" | "examples">(initialTab);

  return (
    <Dialog open={open} onClose={onClose} className="max-w-3xl">
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-line pb-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/10 text-accent">
              <Info size={20} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-fg">How HRMS Policies Work</h2>
              <p className="text-xs text-fg-subtle">
                A simple guide to configuring attendance working hours and leave entitlement pools.
              </p>
            </div>
          </div>
          <Segmented
            value={tab}
            onChange={(v) => setTab(v as typeof tab)}
            items={[
              { value: "leave", label: "Leave System", icon: Layers },
              { value: "attendance", label: "Attendance & Shifts", icon: Clock },
              { value: "examples", label: "Setup Examples", icon: Sparkles },
            ]}
          />
        </div>

        {/* Tab 1: Leave System */}
        {tab === "leave" && (
          <div className="space-y-5 text-[13px]">
            <div className="rounded-xl border border-brand-500/20 bg-brand-500/[0.03] p-4 text-xs">
              <span className="font-semibold text-fg block mb-1">
                The 4-Layer Enterprise Leave Model:
              </span>
              <p className="text-fg-subtle">
                In modern HR systems, why someone applies for leave (the reason) is separated from where
                their balance is kept (the accounting ledger). Here is how the pieces connect:
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-line bg-surface p-4">
                <div className="flex items-center gap-2 text-accent font-semibold mb-1.5">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-brand-500/10 text-xs">1</span>
                  <span>Leave Types (The Application Reason)</span>
                </div>
                <p className="text-xs text-fg-subtle">
                  What employees select in dropdowns: <b>Casual Leave</b>, <b>Sick Leave</b>, <b>Paid Leave</b>, <b>LWP</b>, <b>Maternity</b>. Defines notice periods, doctor's notes, and half-day rules.
                </p>
              </div>

              <div className="rounded-xl border border-line bg-surface p-4">
                <div className="flex items-center gap-2 text-accent font-semibold mb-1.5">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-brand-500/10 text-xs">2</span>
                  <span>Balance Buckets (The Accounting Pool)</span>
                </div>
                <p className="text-xs text-fg-subtle">
                  The actual balance account: <b>PL_BAL</b>, <b>SL_BAL</b>, <b>LWP_BAL</b>. Maintains the monthly ledger (opening, credited, taken, closing). Mapped 1:1 or shared across multiple types.
                </p>
              </div>

              <div className="rounded-xl border border-line bg-surface p-4">
                <div className="flex items-center gap-2 text-accent font-semibold mb-1.5">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-brand-500/10 text-xs">3</span>
                  <span>Policy Sets (The Entitlement Rules)</span>
                </div>
                <p className="text-xs text-fg-subtle">
                  Determines how many days are given: annual quota (e.g. 18 days/yr), monthly accrual rate, year-end carry forward limits, encashment, and probation restrictions.
                </p>
              </div>

              <div className="rounded-xl border border-line bg-surface p-4">
                <div className="flex items-center gap-2 text-accent font-semibold mb-1.5">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-brand-500/10 text-xs">4</span>
                  <span>Scope Assignments (Who Gets It)</span>
                </div>
                <p className="text-xs text-fg-subtle">
                  Assign policy sets hierarchically: Whole Company default ➔ Department overrides (e.g. Factory vs HQ) ➔ Individual employee overrides.
                </p>
              </div>
            </div>

            {/* Application Flow */}
            <div className="rounded-xl border border-line p-4 bg-panel">
              <p className="eyebrow mb-3">Lifecycle of a Leave Application</p>
              <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-center text-xs">
                <div className="rounded-lg bg-surface border border-line p-2.5 flex-1 w-full">
                  <p className="font-semibold text-fg">1. Employee Applies</p>
                  <p className="text-fg-subtle mt-0.5">Validates against available bucket balance</p>
                </div>
                <ArrowRight size={14} className="text-fg-subtle shrink-0 hidden sm:block" />
                <div className="rounded-lg bg-warning/10 border border-warning/20 p-2.5 flex-1 w-full text-warning">
                  <p className="font-semibold">2. Balance Held</p>
                  <p className="text-xs opacity-90 mt-0.5">Days placed on hold so they can't be double-booked</p>
                </div>
                <ArrowRight size={14} className="text-fg-subtle shrink-0 hidden sm:block" />
                <div className="rounded-lg bg-success/10 border border-success/20 p-2.5 flex-1 w-full text-success">
                  <p className="font-semibold">3. Approval</p>
                  <p className="text-xs opacity-90 mt-0.5">Hold converts to Taken and updates ledger</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Attendance System */}
        {tab === "attendance" && (
          <div className="space-y-4 text-[13px]">
            <p className="text-xs text-fg-subtle">
              Attendance policies define daily shift schedules, grace tolerances, overtime computation,
              and missed punch correction approval workflows.
            </p>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-line bg-surface p-4 space-y-1">
                <span className="font-semibold text-fg text-xs flex items-center gap-1.5">
                  <Clock size={14} className="text-accent" /> Work Shifts & Breaks
                </span>
                <p className="text-xs text-fg-subtle">
                  Define start time and total working hours. End time is calculated automatically based
                  on total hours plus break time. Lunch breaks can be automatically deducted.
                </p>
              </div>

              <div className="rounded-xl border border-line bg-surface p-4 space-y-1">
                <span className="font-semibold text-fg text-xs flex items-center gap-1.5">
                  <Shield size={14} className="text-accent" /> Grace & Rounding
                </span>
                <p className="text-xs text-fg-subtle">
                  Allowable delay window (e.g. 15 min late arrival grace) before an employee is flagged
                  as late. Punch times can round up, down, or to nearest 5/15 minutes.
                </p>
              </div>

              <div className="rounded-xl border border-line bg-surface p-4 space-y-1">
                <span className="font-semibold text-fg text-xs flex items-center gap-1.5">
                  <FileText size={14} className="text-accent" /> Overtime (OT)
                </span>
                <p className="text-xs text-fg-subtle">
                  Extra time worked past normal hours is automatically recognized once exceeding the
                  qualifying threshold (e.g. 30 min), calculated at the assigned OT multiplier (e.g. 1.5×).
                </p>
              </div>

              <div className="rounded-xl border border-line bg-surface p-4 space-y-1">
                <span className="font-semibold text-fg text-xs flex items-center gap-1.5">
                  <Building2 size={14} className="text-accent" /> Punch Corrections
                </span>
                <p className="text-xs text-fg-subtle">
                  Missed punches or device failures can be corrected by employees, routed to managers
                  for 1, 2, or 3-level approval before applying to attendance records.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Setup Examples */}
        {tab === "examples" && (
          <div className="space-y-4 text-[13px]">
            <div className="rounded-xl border border-line p-4 bg-surface space-y-2">
              <span className="font-semibold text-fg text-xs flex items-center gap-2">
                <CheckCircle2 size={14} className="text-success" /> Example A: Standard 1-to-1 Mapping (Most Common)
              </span>
              <p className="text-xs text-fg-subtle">
                Each leave type draws from its own separate balance pool:
              </p>
              <div className="grid grid-cols-3 gap-2 text-xs font-mono bg-muted/30 p-2.5 rounded-lg border border-line">
                <div>Casual Leave ➔ <b>CL_BAL</b></div>
                <div>Sick Leave ➔ <b>SL_BAL</b></div>
                <div>Privilege Leave ➔ <b>PL_BAL</b></div>
              </div>
            </div>

            <div className="rounded-xl border border-line p-4 bg-surface space-y-2">
              <span className="font-semibold text-fg text-xs flex items-center gap-2">
                <CheckCircle2 size={14} className="text-success" /> Example B: Consolidated Paid Time Off (PTO)
              </span>
              <p className="text-xs text-fg-subtle">
                Employees can request either "Casual Leave" or "Sick Leave", but both draw from a single pooled "Paid Leave" bucket of 24 days.
              </p>
              <div className="text-xs font-mono bg-muted/30 p-2.5 rounded-lg border border-line">
                [Casual Leave] + [Sick Leave] ➔ both mapped to ➔ <b>PL_BAL (24 days/yr pool)</b>
              </div>
            </div>

            <div className="rounded-xl border border-line p-4 bg-surface space-y-2">
              <span className="font-semibold text-fg text-xs flex items-center gap-2">
                <CheckCircle2 size={14} className="text-success" /> Example C: Leave Without Pay (LWP)
              </span>
              <p className="text-xs text-fg-subtle">
                Leave Without Pay is mapped to an unlimited bucket (<b className="font-mono">LWP_BAL</b>). It has no available balance restrictions, allowing employees to request unpaid days off which flow directly to payroll deductions.
              </p>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-line pt-4">
          <p className="text-xs text-fg-subtle flex items-center gap-1">
            <HelpCircle size={13} /> Need help? Use standard presets for 1-click configuration.
          </p>
          <button className="btn-primary btn-sm" onClick={onClose}>
            Got it
          </button>
        </div>
      </div>
    </Dialog>
  );
}

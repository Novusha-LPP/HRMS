import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { format, parseISO, subDays, addDays, isAfter, startOfDay } from "date-fns";
import {
  Users, UserCheck, Timer, Umbrella, ChevronLeft, ChevronRight,
  Download, Search, X, Eye, ExternalLink, Coffee, ArrowDownRight,
  ArrowUpRight, MapPin,
} from "lucide-react";
import { timeApi, type DailyEmployeeRecord, type DailyAnalysisResponse, type TodayStatus } from "../api/time";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { AreaChart, BarList, Donut, Legend, type AreaPoint } from "../components/ui/Charts";
import { CHART } from "../components/ui/chartPalette";
import { Avatar } from "../components/ui/Avatar";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Tabs } from "../components/ui/Tabs";
import { Sheet } from "../components/ui/Overlay";
import { useToast, errorMessage } from "../components/ui/Toast";
import { Skeleton, EmptyState, Notice } from "../components/ui/Feedback";

type StatusTab = "ALL" | "PRESENT" | "LATE" | "ABSENT" | "ON_LEAVE" | "HALF_DAY";

// Overtime is policy-computed but requires a human review (see
// /v1/time/overtime/pending) before it's "approved" — these keep the label
// honest about which of those three states a given day is actually in,
// instead of always claiming "Approved".
const OT_LABEL: Record<string, string> = {
  NONE: "Overtime", PENDING: "Overtime — pending review", APPROVED: "Approved overtime", REJECTED: "Overtime — rejected",
};
const OT_TONE: Record<string, string> = {
  NONE: "bg-muted text-fg-muted", PENDING: "bg-warning/10 text-warning", APPROVED: "bg-success/10 text-success", REJECTED: "bg-danger/10 text-danger",
};
const OT_TEXT_TONE: Record<string, string> = {
  NONE: "text-fg-muted", PENDING: "text-warning", APPROVED: "text-success", REJECTED: "text-danger",
};

function fmtHours(minutes: number): string {
  if (!minutes || minutes <= 0) return "0h 0m";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}

function fmtTime(isoString?: string | null): string {
  if (!isoString) return "—";
  try {
    const d = new Date(isoString);
    return format(d, "hh:mm a");
  } catch {
    return "—";
  }
}

function fmtFriendlyDate(dateStr: string): string {
  try {
    const d = new Date(`${dateStr}T00:00:00`);
    return format(d, "EEEE, d MMMM yyyy");
  } catch {
    return dateStr;
  }
}

function exportDailyAnalysisCsv(dateStr: string, employees: DailyEmployeeRecord[]) {
  const headers = [
    "Employee ID",
    "Employee Name",
    "Email",
    "Department",
    "Designation",
    "Work Date",
    "Attendance Status",
    "First Check-in",
    "Last Check-out",
    "Effective Minutes",
    "Effective Hours",
    "Gross Minutes",
    "Break Minutes",
    "Late By (Minutes)",
    "Early Departure (Minutes)",
    "Overtime (Minutes)",
    "Leave Type",
    "Punches Count",
  ];

  const esc = (v: unknown) => {
    const str = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };

  const rows = employees.map((emp) => [
    emp.employee_number,
    emp.name,
    emp.email ?? "",
    emp.department ?? "",
    emp.designation ?? "",
    dateStr,
    emp.status,
    emp.first_punch_in ? format(new Date(emp.first_punch_in), "yyyy-MM-dd HH:mm:ss") : "",
    emp.last_punch_out ? format(new Date(emp.last_punch_out), "yyyy-MM-dd HH:mm:ss") : "",
    emp.effective_minutes,
    (emp.effective_minutes / 60).toFixed(2),
    emp.gross_minutes,
    emp.break_minutes,
    emp.late_by_minutes,
    emp.early_departure_minutes,
    emp.overtime_minutes,
    emp.leave_type ?? "",
    emp.punches_count,
  ]);

  const csvContent = [headers.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.setAttribute("download", `daily-attendance-analysis-${dateStr}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function DailyAnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Date selection state
  const todayStr = format(new Date(), "yyyy-MM-dd");
  const initialDate = searchParams.get("date") || todayStr;
  const [selectedDate, setSelectedDate] = useState<string>(initialDate);

  // Filters state
  const [statusFilter, setStatusFilter] = useState<StatusTab>("ALL");
  const [deptFilter, setDeptFilter] = useState<string>(searchParams.get("dept") || "");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Pagination state
  const [page, setPage] = useState<number>(1);
  const perPage = 10;
  const [exporting, setExporting] = useState(false);
  const toast = useToast();

  // Inspection Drawer
  const [inspectEmployee, setInspectEmployee] = useState<DailyEmployeeRecord | null>(null);

  // Sync date change to URL
  const handleDateChange = (newDate: string) => {
    setSelectedDate(newDate);
    setPage(1);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("date", newDate);
      return next;
    });
  };

  const isSelectedToday = selectedDate === todayStr;
  const isFutureDate = isAfter(parseISO(selectedDate), startOfDay(new Date()));

  // Fetch Daily Analysis from backend API
  const { data, isPending, isError, refetch } = useQuery<DailyAnalysisResponse>({
    queryKey: ["daily-analysis", selectedDate, deptFilter, statusFilter, searchQuery, page],
    queryFn: () =>
      timeApi.dailyAnalysis({
        work_date: selectedDate,
        limit: perPage, offset: (page - 1) * perPage,
        department: deptFilter || undefined,
        status: statusFilter === "ALL" ? undefined : statusFilter,
        search: searchQuery.trim() || undefined,
      }),
  });

  // Fetch employee punches when drawer is open
  const employeePunchesQuery = useQuery<TodayStatus>({
    queryKey: ["employee-day-punches", inspectEmployee?.employment_id, selectedDate],
    queryFn: () => timeApi.today(inspectEmployee!.employment_id, selectedDate),
    enabled: !!inspectEmployee,
  });

  const metrics = data?.metrics ?? {
    total_headcount: 0,
    present_count: 0,
    on_time_count: 0,
    late_count: 0,
    absent_count: 0,
    on_leave_count: 0,
    half_day_count: 0,
    presence_rate: 0,
    average_work_minutes: 0,
    total_overtime_minutes: 0,
  };

  const employees = data?.employees ?? [];
  const deptStats = data?.department_stats ?? [];
  const hourlyArrivals = data?.hourly_arrivals ?? [];

  // Hourly Arrival Trend Area Points
  const hourlyPoints: AreaPoint[] =
    hourlyArrivals.length > 1
      ? hourlyArrivals.map((ha) => ({
          label: ha.hour,
          value: ha.count,
          detail: (
            <div className="tabular-nums">
              <b className="font-semibold text-fg">{ha.count}</b> check-ins clocked at {ha.hour}
            </div>
          ),
        }))
      : [
          { label: "08:00", value: 0 },
          { label: "09:00", value: 0 },
          { label: "10:00", value: 0 },
          { label: "11:00", value: 0 },
        ];

  const peakHourlyCount = Math.max(...hourlyPoints.map((h) => h.value), 0);
  // Axis top is a multiple of 4 (its four gridline steps) so every tick label is a whole number,
  // with a floor so a near-empty day doesn't stretch one check-in to full height.
  const maxHourlyCount = Math.max(Math.ceil(peakHourlyCount / 4) * 4, 4);

  // Unique departments for filter dropdown
  const allDepartments = Array.from(
    new Set(deptStats.map((d) => d.department).filter(Boolean)),
  ).sort();

  // Client pagination
  const totalEmployees = data?.total_filtered ?? employees.length;
  const totalPages = Math.max(Math.ceil(totalEmployees / perPage), 1);
  const paginatedEmployees = employees;
  const exportAll = async () => {
    setExporting(true);
    try {
      const records: DailyEmployeeRecord[] = [];
      for (let offset = 0; ; offset += 500) {
        const result = await timeApi.dailyAnalysis({ work_date: selectedDate,
          department: deptFilter || undefined, status: statusFilter === "ALL" ? undefined : statusFilter,
          search: searchQuery.trim() || undefined, limit: 500, offset });
        records.push(...result.employees);
        if (records.length >= result.total_filtered || result.employees.length === 0) break;
      }
      exportDailyAnalysisCsv(selectedDate, records);
    } catch (e) { toast.error("Couldn’t export attendance", errorMessage(e)); }
    finally { setExporting(false); }
  };

  const clearFilters = () => {
    setStatusFilter("ALL");
    setDeptFilter("");
    setSearchQuery("");
    setPage(1);
  };

  const hasActiveFilters = statusFilter !== "ALL" || !!deptFilter || !!searchQuery.trim();
  const punctualityPct =
    metrics.present_count > 0 ? Math.round((metrics.on_time_count / metrics.present_count) * 100) : 0;

  return (
    <div className="space-y-6">
      {/* Page Header with Controls */}
      <PageHeader
        title="Daily Employee Analysis"
        description={`Workforce presence, punctuality and work hours analysis for ${fmtFriendlyDate(selectedDate)}.`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {/* Date Navigation matching Attendance/Dashboard style */}
            <div className="flex items-center gap-1 rounded-lg border border-line bg-surface p-1 shadow-xs">
              <button
                type="button"
                className="btn-icon h-7 w-7"
                title="Previous Day"
                onClick={() => handleDateChange(format(subDays(parseISO(selectedDate), 1), "yyyy-MM-dd"))}
              >
                <ChevronLeft size={15} />
              </button>

              <input
                type="date"
                value={selectedDate}
                max={todayStr}
                onChange={(e) => e.target.value && handleDateChange(e.target.value)}
                className="cursor-pointer border-0 bg-transparent px-1.5 py-0.5 text-xs font-semibold text-fg outline-none"
                aria-label="Select Date"
              />

              <button
                type="button"
                className="btn-icon h-7 w-7"
                title="Next Day"
                disabled={isFutureDate || isSelectedToday}
                onClick={() => handleDateChange(format(addDays(parseISO(selectedDate), 1), "yyyy-MM-dd"))}
              >
                <ChevronRight size={15} />
              </button>
            </div>

            {!isSelectedToday && (
              <button
                type="button"
                className="btn-ghost btn-sm text-xs"
                onClick={() => handleDateChange(todayStr)}
              >
                Today
              </button>
            )}

            <button
              type="button"
              className="btn-secondary btn-sm gap-1.5"
              onClick={() => { void exportAll(); }}
              disabled={totalEmployees === 0 || exporting}
            >
              <Download size={13} />
              <span>Export CSV</span>
            </button>
          </div>
        }
      />

      {isError && (
        <Notice
          title="Could not load daily analysis"
          tone="warning"
          action={
            <button className="btn-secondary btn-sm" onClick={() => refetch()}>
              Retry
            </button>
          }
        >
          An unexpected error occurred while compiling attendance records for this date.
        </Notice>
      )}

      {/* 4 StatCards Grid — matching Dashboard UI */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Headcount"
          icon={Users}
          loading={isPending}
          value={metrics.total_headcount}
          hint="active roster for date"
        />
        <StatCard
          label="Present today"
          icon={UserCheck}
          loading={isPending}
          value={metrics.present_count}
          hint={`${metrics.presence_rate}% of workforce`}
          delta={metrics.on_time_count}
          deltaSuffix=" on time"
        />
        <StatCard
          label="Late arrivals"
          icon={Timer}
          loading={isPending}
          value={metrics.late_count}
          hint="grace window exceeded"
          invertDelta={true}
          delta={metrics.late_count}
          deltaSuffix=" late"
        />
        <StatCard
          label="On leave & absent"
          icon={Umbrella}
          loading={isPending}
          value={metrics.on_leave_count + metrics.absent_count}
          hint={`${metrics.absent_count} unplanned · ${metrics.on_leave_count} on leave`}
        />
      </div>

      {/* Row 2: Hourly Arrival Trend (lg:col-span-2) + Attendance Share Donut (lg:col-span-1) */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <div className="card-header">
            <div>
              <h3 className="card-title">Hourly arrival pattern</h3>
              <p className="card-desc">Check-in distribution and punch velocity by hour</p>
            </div>
            <span className="text-xs font-medium text-fg-subtle">
              {peakHourlyCount > 0 ? `Peak: ${peakHourlyCount} check-ins` : "No check-ins yet"}
            </span>
          </div>
          <div className="px-5 pb-5">
            {isPending ? (
              <Skeleton className="h-[220px] w-full rounded-lg" />
            ) : (
              <AreaChart
                data={hourlyPoints}
                min={0}
                max={maxHourlyCount}
                color={CHART.present}
                unit=" in"
              />
            )}
          </div>
        </div>

        {/* Attendance Share Donut — exact Dashboard UI */}
        <div className="card">
          <div className="card-header">
            <div>
              <h3 className="card-title">Attendance share</h3>
              <p className="card-desc">{fmtFriendlyDate(selectedDate)}</p>
            </div>
            <span className="text-xs font-semibold tabular-nums text-success">
              {metrics.presence_rate}% rate
            </span>
          </div>
          <div className="flex flex-col items-center gap-6 px-5 pb-5 sm:flex-row lg:flex-col xl:flex-row">
            {isPending ? (
              <Skeleton className="h-[152px] w-[152px] rounded-full" />
            ) : (
              <Donut
                segments={[
                  { label: "On time", value: metrics.on_time_count, color: CHART.present },
                  { label: "Late", value: metrics.late_count, color: CHART.late },
                  { label: "Absent", value: metrics.absent_count, color: CHART.absent },
                  { label: "On leave", value: metrics.on_leave_count, color: CHART.leave },
                ]}
              >
                <span className="text-2xl font-semibold tabular-nums text-fg">{metrics.presence_rate}%</span>
                <span className="text-[11px] text-fg-subtle">present</span>
              </Donut>
            )}
            <div className="w-full flex-1">
              <Legend
                items={[
                  { label: "On time", color: CHART.present, value: isPending ? "–" : metrics.on_time_count },
                  { label: "Late", color: CHART.late, value: isPending ? "–" : metrics.late_count },
                  { label: "Absent", color: CHART.absent, value: isPending ? "–" : metrics.absent_count },
                  { label: "On leave", color: CHART.leave, value: isPending ? "–" : metrics.on_leave_count },
                ]}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Row 3: Department Breakdown + Shift Adherence Metrics */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Department Presence List */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">Presence by department</h3>
            {deptFilter ? (
              <button
                type="button"
                onClick={() => {
                  setDeptFilter("");
                  setPage(1);
                }}
                className="btn-ghost btn-sm text-xs"
              >
                Clear filter
              </button>
            ) : (
              <span className="text-xs text-fg-subtle">{deptStats.length} depts</span>
            )}
          </div>
          <div className="px-5 pb-5">
            {isPending ? (
              <div className="space-y-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            ) : deptStats.length === 0 ? (
              <p className="text-xs text-fg-subtle">No department data for this date.</p>
            ) : (
              <BarList
                items={deptStats.map((d) => ({
                  label: d.department,
                  value: d.presence_rate,
                  color: d.presence_rate >= 80 ? "rgba(16, 185, 129, 0.2)" : "rgba(245, 158, 11, 0.2)",
                }))}
                formatValue={(v) => `${v}%`}
              />
            )}
          </div>
        </div>

        {/* Shift Adherence & Hours Summary */}
        <div className="card lg:col-span-2">
          <div className="card-header">
            <div>
              <h3 className="card-title">Shift adherence & work hours</h3>
              <p className="card-desc">Aggregate duration, overtime and punctuality metrics</p>
            </div>
          </div>
          <div className="grid gap-3 p-5 sm:grid-cols-2">
            <div className="rounded-xl border border-line bg-panel/50 p-4">
              <span className="text-xs font-medium text-fg-subtle">Average Working Time</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-xl font-bold tabular-nums text-fg">
                  {fmtHours(metrics.average_work_minutes)}
                </span>
                <span className="text-xs text-fg-subtle">net effective</span>
              </div>
              <p className="mt-2 text-[11px] text-fg-subtle">Calculated across active present employees</p>
            </div>

            <div className="rounded-xl border border-line bg-panel/50 p-4">
              <span className="text-xs font-medium text-fg-subtle">Total Overtime Clocked</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-xl font-bold tabular-nums text-fg">
                  {fmtHours(metrics.total_overtime_minutes)}
                </span>
                <span className="text-xs text-success font-medium">approved</span>
              </div>
              <p className="mt-2 text-[11px] text-fg-subtle">Total time recorded beyond standard 8-hour shift</p>
            </div>

            <div className="rounded-xl border border-line bg-panel/50 p-4">
              <span className="text-xs font-medium text-fg-subtle">Punctuality Score</span>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-xl font-bold tabular-nums text-fg">{punctualityPct}%</span>
                <span className="text-xs text-fg-subtle">of present staff</span>
              </div>
              <p className="mt-2 text-[11px] text-fg-subtle">Arrived within designated shift grace window</p>
            </div>
          </div>
        </div>
      </div>

      {/* Row 4: Daily Employee Roster — using standard Dashboard card & tbl styling */}
      <div className="card overflow-hidden">
        <div className="card-header border-b border-line">
          <div>
            <h3 className="card-title">Employee daily roster</h3>
            <p className="card-desc">Individual check-in, check-out and duration logs</p>
          </div>
          <span className="text-xs text-fg-subtle">
            {totalEmployees} {totalEmployees === 1 ? "record" : "records"}
          </span>
        </div>

        {/* Status Tabs Header */}
        <div className="px-5 pt-1">
          <Tabs<StatusTab>
            value={statusFilter}
            onChange={(tab) => {
              setStatusFilter(tab);
              setPage(1);
            }}
            items={[
              { value: "ALL", label: "All", count: isPending ? undefined : metrics.total_headcount },
              { value: "PRESENT", label: "Present", count: isPending ? undefined : metrics.present_count },
              { value: "LATE", label: "Late in", count: isPending ? undefined : metrics.late_count },
              { value: "ABSENT", label: "Absent", count: isPending ? undefined : metrics.absent_count },
              { value: "ON_LEAVE", label: "On leave", count: isPending ? undefined : metrics.on_leave_count },
              { value: "HALF_DAY", label: "Half day", count: isPending ? undefined : metrics.half_day_count },
            ]}
          />
        </div>

        {/* Filter and Search Bar matching EmployeePage */}
        <div className="flex flex-col gap-2 border-b border-line px-5 py-3 sm:flex-row sm:items-center">
          <div className="relative flex-1 sm:max-w-xs">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
              placeholder="Search name, ID or email"
              className="input pl-9"
              aria-label="Search employees"
            />
          </div>

          {allDepartments.length > 0 && (
            <select
              value={deptFilter}
              onChange={(e) => {
                setDeptFilter(e.target.value);
                setPage(1);
              }}
              className="input sm:w-44"
              aria-label="Filter department"
            >
              <option value="">All departments</option>
              {allDepartments.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          )}

          {hasActiveFilters && (
            <button type="button" onClick={clearFilters} className="btn-ghost btn-sm">
              <X size={13} /> Clear
            </button>
          )}

          <span className="text-xs text-fg-subtle sm:ml-auto">
            Showing {paginatedEmployees.length} of {totalEmployees} employees
          </span>
        </div>

        {/* Table Body using standard .tbl styling */}
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Employee</th>
                <th>Department</th>
                <th>Status</th>
                <th>Check in</th>
                <th>Check out</th>
                <th>Worked</th>
                <th>Overtime</th>
                <th className="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {isPending ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    <td>
                      <div className="flex items-center gap-3">
                        <Skeleton className="h-8 w-8 rounded-full" />
                        <div className="space-y-1">
                          <Skeleton className="h-3.5 w-28" />
                          <Skeleton className="h-3 w-16" />
                        </div>
                      </div>
                    </td>
                    <td><Skeleton className="h-3.5 w-24" /></td>
                    <td><Skeleton className="h-5 w-20 rounded-full" /></td>
                    <td><Skeleton className="h-3.5 w-20" /></td>
                    <td><Skeleton className="h-3.5 w-20" /></td>
                    <td><Skeleton className="h-3.5 w-16" /></td>
                    <td><Skeleton className="h-3.5 w-14" /></td>
                    <td className="text-right"><Skeleton className="ml-auto h-7 w-16 rounded" /></td>
                  </tr>
                ))
              ) : employees.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12">
                    <EmptyState
                      title="No employee records found"
                      description={
                        hasActiveFilters
                          ? "No employees match your search and filter criteria for this date."
                          : "No employee attendance records found for this date."
                      }
                      action={
                        hasActiveFilters ? (
                          <button type="button" className="btn-secondary btn-sm" onClick={clearFilters}>
                            Clear filters
                          </button>
                        ) : undefined
                      }
                    />
                  </td>
                </tr>
              ) : (
                paginatedEmployees.map((emp) => {
                  const isLate = emp.late_by_minutes > 0;
                  const hasOvertime = emp.overtime_minutes > 0;

                  return (
                    <tr
                      key={emp.employment_id}
                      onClick={() => setInspectEmployee(emp)}
                      className="cursor-pointer"
                    >
                      {/* Employee Profile */}
                      <td>
                        <div className="flex items-center gap-3">
                          <Avatar name={emp.name} size="sm" />
                          <div className="min-w-0 leading-tight">
                            <span className="block truncate font-medium text-fg">
                              {emp.name}
                            </span>
                            <span className="block truncate text-xs text-fg-subtle">
                              {emp.employee_number}
                              {emp.email ? ` · ${emp.email}` : ""}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* Department & Role */}
                      <td>
                        <div className="min-w-0 leading-tight">
                          <p className="truncate font-medium text-fg">{emp.department || "—"}</p>
                          <p className="truncate text-xs text-fg-subtle">{emp.designation || "—"}</p>
                        </div>
                      </td>

                      {/* Status */}
                      <td>
                        <div className="flex items-center gap-1.5">
                          <StatusBadge status={emp.status} />
                          {emp.leave_type && (
                            <span className="badge badge-info text-[10px]">
                              {emp.leave_type}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* First Check-In */}
                      <td className="tabular-nums">
                        <div className="flex items-center gap-1.5">
                          <span>{fmtTime(emp.first_punch_in)}</span>
                          {isLate && (
                            <span className="badge badge-warning text-[10px]">
                              +{fmtHours(emp.late_by_minutes)}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Last Check-Out */}
                      <td className="tabular-nums">
                        {emp.is_currently_in ? (
                          <span className="badge badge-success">
                            Active
                          </span>
                        ) : (
                          <span>{fmtTime(emp.last_punch_out)}</span>
                        )}
                      </td>

                      {/* Worked */}
                      <td className="tabular-nums font-medium text-fg">
                        {fmtHours(emp.effective_minutes)}
                      </td>

                      {/* Overtime */}
                      <td className="tabular-nums">
                        {hasOvertime ? (
                          <span className={`inline-flex items-center gap-0.5 font-medium ${OT_TEXT_TONE[emp.overtime_status]}`}>
                            <ArrowUpRight size={12} /> +{fmtHours(emp.overtime_minutes)}
                          </span>
                        ) : (
                          <span className="text-fg-subtle">—</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setInspectEmployee(emp);
                          }}
                          className="btn-ghost btn-sm"
                          title="Inspect Day"
                        >
                          <Eye size={13} />
                          <span>Inspect</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination matching EmployeePage */}
        {!isPending && employees.length > 0 && (
          <div className="flex items-center justify-between border-t border-line px-5 py-3 text-xs text-fg-subtle">
            <span>
              Showing {(page - 1) * perPage + 1}–{Math.min(page * perPage, totalEmployees)} of {totalEmployees} employees
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="btn-icon h-7 w-7"
                onClick={() => setPage((p) => Math.max(p - 1, 1))}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="px-2 font-medium text-fg">
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className="btn-icon h-7 w-7"
                onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
                disabled={page >= totalPages}
                aria-label="Next page"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Employee Day Timeline Inspection Drawer */}
      <Sheet
        open={!!inspectEmployee}
        onClose={() => setInspectEmployee(null)}
        title={
          inspectEmployee ? (
            <div className="flex items-center gap-3">
              <Avatar name={inspectEmployee.name} size="md" />
              <div>
                <h3 className="font-semibold text-fg">{inspectEmployee.name}</h3>
                <p className="text-xs text-fg-subtle">
                  {inspectEmployee.employee_number} · {inspectEmployee.department || "General"}
                </p>
              </div>
            </div>
          ) : (
            "Day Inspector"
          )
        }
        description={inspectEmployee ? fmtFriendlyDate(selectedDate) : undefined}
        footer={
          inspectEmployee ? (
            <div className="flex w-full items-center justify-between">
              <Link
                to={`/corrections?new=1`}
                className="btn-secondary btn-sm gap-1.5"
              >
                <span>Request correction</span>
              </Link>
              <Link
                to={`/employees`}
                className="btn-ghost btn-sm gap-1.5"
              >
                <span>View employee profile</span>
                <ExternalLink size={12} />
              </Link>
            </div>
          ) : undefined
        }
      >
        {inspectEmployee && (
          <div className="space-y-6">
            {/* Status and Metrics Overview Card */}
            <div className="rounded-xl border border-line bg-panel p-4 space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-fg-subtle">Attendance Status</span>
                <StatusBadge status={inspectEmployee.status} />
              </div>

              {inspectEmployee.leave_type && (
                <div className="flex items-center gap-2 rounded-lg bg-info/10 p-3 text-xs text-info">
                  <Umbrella size={16} />
                  <span>Approved Leave: <strong>{inspectEmployee.leave_type}</strong></span>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 pt-1 border-t border-line">
                <div className="rounded-lg bg-surface p-2.5 border border-line">
                  <span className="text-[11px] font-medium text-fg-subtle">First Check-in</span>
                  <div className="mt-0.5 font-semibold text-fg tabular-nums">
                    {fmtTime(inspectEmployee.first_punch_in)}
                  </div>
                  {inspectEmployee.late_by_minutes > 0 && (
                    <span className="text-[10px] font-medium text-warning">
                      +{fmtHours(inspectEmployee.late_by_minutes)} late
                    </span>
                  )}
                </div>

                <div className="rounded-lg bg-surface p-2.5 border border-line">
                  <span className="text-[11px] font-medium text-fg-subtle">Last Check-out</span>
                  <div className="mt-0.5 font-semibold text-fg tabular-nums">
                    {inspectEmployee.is_currently_in ? (
                      <span className="text-success font-semibold">Active</span>
                    ) : (
                      fmtTime(inspectEmployee.last_punch_out)
                    )}
                  </div>
                </div>

                <div className="rounded-lg bg-surface p-2.5 border border-line">
                  <span className="text-[11px] font-medium text-fg-subtle">Effective Hours</span>
                  <div className="mt-0.5 font-semibold text-fg tabular-nums">
                    {fmtHours(inspectEmployee.effective_minutes)}
                  </div>
                  <span className="text-[10px] text-fg-subtle">Excluding breaks</span>
                </div>

                <div className="rounded-lg bg-surface p-2.5 border border-line">
                  <span className="text-[11px] font-medium text-fg-subtle">Gross Span</span>
                  <div className="mt-0.5 font-semibold text-fg tabular-nums">
                    {fmtHours(inspectEmployee.gross_minutes)}
                  </div>
                  {inspectEmployee.break_minutes > 0 && (
                    <span className="text-[10px] text-fg-subtle">
                      Break: {fmtHours(inspectEmployee.break_minutes)}
                    </span>
                  )}
                </div>
              </div>

              {inspectEmployee.overtime_minutes > 0 && (
                <div className={`flex items-center justify-between rounded-lg p-2.5 text-xs font-medium ${OT_TONE[inspectEmployee.overtime_status]}`}>
                  <span className="flex items-center gap-1.5">
                    <ArrowUpRight size={14} /> {OT_LABEL[inspectEmployee.overtime_status]}
                  </span>
                  <span className="font-bold tabular-nums">+{fmtHours(inspectEmployee.overtime_minutes)}</span>
                </div>
              )}
            </div>

            {/* Detailed Punch Timeline */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-subtle">
                  Day Punches ({employeePunchesQuery.data?.punches.length ?? inspectEmployee.punches_count})
                </h4>
              </div>

              {employeePunchesQuery.isPending ? (
                <div className="space-y-2">
                  <Skeleton className="h-10 w-full rounded-lg" />
                  <Skeleton className="h-10 w-full rounded-lg" />
                </div>
              ) : (employeePunchesQuery.data?.punches.length ?? 0) === 0 ? (
                <div className="rounded-lg border border-line bg-panel p-5 text-center text-xs text-fg-subtle">
                  {inspectEmployee.status === "ON_LEAVE" ? (
                    <p>Employee is on approved leave.</p>
                  ) : inspectEmployee.status === "ABSENT" ? (
                    <p className="text-danger">Employee was marked absent with no check-in punches recorded.</p>
                  ) : (
                    <p>No punch details available for this date.</p>
                  )}
                </div>
              ) : (
                <div className="relative pl-6 space-y-3 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-line">
                  {employeePunchesQuery.data!.punches.map((punch, idx) => {
                    const isPunchIn = punch.punch_type === "IN";
                    const isPunchOut = punch.punch_type === "OUT";

                    const toneIcon = isPunchIn ? (
                      <ArrowDownRight size={12} className="text-success" />
                    ) : isPunchOut ? (
                      <ArrowUpRight size={12} className="text-danger" />
                    ) : (
                      <Coffee size={12} className="text-warning" />
                    );

                    return (
                      <div key={punch.id || idx} className="relative">
                        <div className="absolute -left-[19px] top-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-line bg-surface shadow-xs">
                          {toneIcon}
                        </div>

                        <div className="rounded-lg border border-line bg-surface p-2.5 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-fg">
                              {punch.punch_type === "IN"
                                ? "Punch in"
                                : punch.punch_type === "OUT"
                                ? "Punch out"
                                : punch.punch_type === "BREAK_START"
                                ? "Break start"
                                : "Break end"}
                            </span>
                            <span className="font-semibold tabular-nums text-fg">
                              {fmtTime(punch.punched_at)}
                            </span>
                          </div>

                          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-fg-subtle">
                            <span className="badge badge-neutral text-[10px]">
                              {punch.source}
                            </span>
                            {punch.is_corrected && (
                              <span className="badge badge-warning text-[10px]">
                                Regularized
                              </span>
                            )}
                            {punch.latitude && punch.longitude && (
                              <span className="inline-flex items-center gap-0.5 text-fg-subtle">
                                <MapPin size={10} />
                                {punch.latitude.toFixed(3)}, {punch.longitude.toFixed(3)}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </Sheet>
    </div>
  );
}

# Export attendance from Reports

1. Open **Reports → Saved reports**.
2. Select **Run** on **Monthly Attendance Summary**, or another saved attendance report.
3. Set the **Date on or after** and **Date on or before** filters.
4. Select **Export Excel** in the same panel. Running the on-screen table is optional.

The download contains an Overview with company comparisons, a filterable Employee
Summary, and company attendance and leave registers with daily logs and worked
hours. Exports read current HRMS records without updating punches, leave requests
or leave ledgers. The reference spreadsheet is not imported into the database.

The existing **Run report** and **Export CSV** actions continue to work as before.
The Excel register does not use the preview's row limit: it includes every matching
employee's selected calendar dates. Exports support up to 62 days and 1,000
employees. Larger selections return an instruction to narrow the filters.

Date, employee, department and location constraints are honored. Department and
location constraints follow the assignment on each work date. A register needs
the full sequence of day statuses, so remove a nonempty status filter before
exporting. Missing, reversed, contradictory or unbounded dates return a specific
validation error instead of exporting a broader period.

The workbook preserves the reference's distinction between fractional attendance,
half-day PL occurrences, PL day quantities and leave-ledger debits. **Total Working
Days** uses the source's paid-day convention, including paid leave, weekly offs and
holidays. Other paid leave remains separate from Privilege Leave.

Ledger balances require complete calendar months, an identifiable existing PL
ledger and leave access. Missing balances remain blank; actual zero balances
remain zero. With department or location filters, the employee's PL ledger still
covers the requested calendar month, while attendance totals cover matching dates.
Punches use each day's policy timezone, and overnight dates remain stored in Excel.

The Excel headcount chart references the company summary cells and includes cached values.
For more than ten companies it shows the ten largest by headcount, as labeled;
all matching companies and employees remain in the workbook tables and registers.

`POST /v1/reports/{report_id}/export-attendance` accepts the same `filters` list as
the report runner. Saved and runtime filters use the same override rules. The
endpoint requires `reports.read`, applies its tenant and employment scope, and
returns a `.xlsx` attachment. It does not expose a separate report page.

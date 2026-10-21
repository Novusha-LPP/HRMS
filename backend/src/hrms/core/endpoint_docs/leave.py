"""Endpoint docs: Leave Management."""

_APPROVER_RULES = """
- If an approval flow covers this request, the caller must be the current step's approver.
  Otherwise they need `leave.approve` over the employee.
- You can't decide your own request, and each level needs a different reviewer.
"""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Unused leave when someone leaves ────────────────────────────────────
    "report_leave_settlements": (
        "Report: leave settled for leavers",
        "What happened to the unused leave of people who left in the date range (default: the "
        "last 90 days): days unused, paid out, lapsed or still held, the rule applied, when a "
        "hold ends and how it ended. Only people your access covers appear. `format=csv` "
        "downloads it as a spreadsheet file.",
    ),
    "list_separation_rules": (
        "List leave rules for leavers",
        "The rules that say what happens to unused leave when someone leaves, including ones "
        "that start in the future. With no rule in force, nothing happens to the balance.",
    ),
    "create_separation_rule": (
        "Add a leave rule for leavers",
        """
Says what happens to unused leave when someone leaves, from a start date.

- **`on_separation`:** `LAPSE` removes the balance, `ENCASH` pays it out (only for leave types
  marked encashable) and `HOLD` keeps it, optionally for `hold_days` days.
- **`max_encash_days`:** only with `ENCASH`. Anything above the cap lapses.
- **`legal_entity_id` and `leave_type_id`:** leave one blank to cover every company or every
  leave type. The most specific rule in force on the last day applies.
- Two live rules can't start on the same date for the same company and leave type (409).
""",
    ),
    "archive_separation_rule": (
        "Remove a leave rule for leavers",
        "Archives the rule. Leavers already settled keep what was done for them.",
    ),
    "preview_separation_settlement": (
        "Preview leave settlement for a leaver",
        "What would happen to this person's unused leave if they left on `as_of` (default "
        "today): the unused days per leave type and whether each lapses, is encashed or is held. "
        "Nothing is changed. Needs `leave.read` over the employee.",
    ),
    "list_separation_settlements": (
        "List leave settlements for an employee",
        "What was done with this person's unused leave each time they left: days encashed, "
        "lapsed or held, and how a hold ended (lapsed, or restored when they rejoined).",
    ),
    # ─── Leave types ─────────────────────────────────────────────────────────
    "list_leave_types": (
        "List leave types",
        "The active leave types (Casual, Sick, Earned, Comp-off, and so on) and their rules. "
        "Any signed-in user can read them, for example to fill a leave form.",
    ),
    "list_archived_leave_types": (
        "List archived leave types",
        "Leave types that were removed. Restore one with "
        "`POST /v1/leave/types/{leave_type_id}/restore`.",
    ),
    "restore_leave_type": (
        "Restore a leave type",
        "Brings back an archived leave type.",
    ),
    "create_leave_type": (
        "Create a leave type",
        """
Adds a leave type.

- **Entitlement:** `days_per_year`, `accrual_enabled`, `carry_forward` and
  `max_carry_forward_days`. These apply when no leave policy set covers the employee.
- **Approval:** `requires_approval` and `approval_levels` (1–3). Cancelling approved leave uses
  `cancel_requires_approval` and `cancel_approval_levels`.
- **Limits:** `min_days_per_application`, `max_days_per_application`, `advance_notice_days`
  and `requires_document`.
- `is_paid`, `encashable`, `is_comp_off`, and a display `color`.
""",
    ),
    "update_leave_type": (
        "Update a leave type",
        "Changes the fields you send. An archived type must be restored first (`409`). Needs "
        "`leave.write` across all companies.",
    ),
    "remove_leave_type": (
        "Remove a leave type",
        "Archives a leave type so it can't be applied for. Past applications and balances are "
        "kept. The built-in comp-off type can't be removed (`409`).",
    ),
    # ─── Balances and ledger ─────────────────────────────────────────────────
    "list_balances": (
        "Get leave balances",
        """
An employee's balance for each leave type in a financial year. Leave out `employment_id` for
the caller's own balances.

`year` is the label of the financial year it starts in. For example, `2026` means FY 2026-27
when the company's year starts in April. It defaults to the current one.

Each row shows the opening balance carried forward (`carry_forward_days`), days credited this
year (`allocated_days`), and used, held and available days. A type with no activity yet this
year isn't listed.
""",
    ),
    "grant_comp_off": (
        "Grant compensatory off",
        "Credits comp-off days (default 1) to an employee for working on `work_date`, usually "
        "a weekly off or holiday. Only one grant is allowed per employee and date (`400`).",
    ),
    "encash_leave": (
        "Encash leave",
        "Converts unused days of an `encashable` leave type to pay, and debits them from the "
        "balance. Returns `400` if the type isn't encashable or there aren't enough days.",
    ),
    "adjust_balance": (
        "Adjust a leave balance",
        """
Posts one manual credit (positive `quantity`) or debit (negative `quantity`) to an employee's
balance, with a `reason`.

- `kind: "OPENING"` loads an opening balance carried over from a previous system.
- `kind: "ADJUSTMENT"` corrects a mistake.

Both are recorded in the transaction journal.
""",
    ),
    "run_accrual": (
        "Run monthly accrual",
        """
Credits leave for `period` (`YYYY-MM`, default the current month) to every eligible employee,
following their leave policy, or the leave type's own settings when no policy applies.

Running it again for the same period does nothing, so it is safe to retry. It does not
backfill months that were skipped, so run each one.
""",
    ),
    "close_year_end": (
        "Close the leave year",
        """
Closes financial year `fy_year`. Balances above the carry-forward limit lapse (posted as
`LAPSE`), and what remains becomes next year's opening balance. Run it once, after the year
ends.
""",
    ),
    "get_leave_ledger": (
        "Get the monthly leave ledger",
        "Month-by-month balance movement for one employee: opening, accrued, granted, held, "
        "adjusted, taken, lapsed and closing, per balance bucket. Filter by `bucket_id` and by "
        "`fy_year` or `calendar_year`.",
    ),
    "get_leave_transactions": (
        "Get leave transactions",
        "Every individual posting behind an employee's balances (accrual, hold, release, taken, "
        "reversal, adjustment, lapse, encashment), optionally limited to a bucket and a date "
        "range.",
    ),
    # ─── Applications ────────────────────────────────────────────────────────
    "leave_management_list_applications": (
        "List leave applications",
        """
Leave applications the caller can see. Without filters, this is everything in their scope.
Filter by `employment_id` and `status`.

Sorted newest first, with drafts at the top. **Paging:** pass the `id` of the last item as
`after` to get the next page. `limit` caps the page size.
""",
    ),
    "application_summary": (
        "Leave application summary",
        "Counts of applications by status, and approved days by leave type, across the "
        "caller's scope. Optionally for one `legal_entity_id`.",
    ),
    "create_application": (
        "Create a leave application",
        """
Creates a leave application as a **`DRAFT`**. Nothing is booked until you call
`POST /v1/leave/applications/{app_id}/submit`.

- The number of days counts working days only. Weekly offs and holidays are not counted.
  Use `half_day_option` (`FIRST_HALF` or `SECOND_HALF`) for a half day.
- It is checked against the leave type's rules: minimum and maximum days, advance notice, and
  a supporting document (`document_id`, one of the employee's KYC documents) when required.
  It also can't overlap another active application (`409`).
- Leave out `employment_id` to apply for yourself. Applying for someone else needs
  `leave.write` over them.
""",
    ),
    "submit_application": (
        "Submit a leave application",
        """
Sends a `DRAFT` for approval and **holds** the days from the balance. Returns `409` when the
balance is too low.

The application moves to `PENDING_L1`, or straight to `APPROVED` when neither the leave type
nor an approval flow requires approval.
""",
    ),
    "approve_application": (
        "Approve a leave application",
        f"""
Approves at the current level. At the last level, the application becomes `APPROVED` and the
held days are recorded as taken. Before that, it moves to the next level.
{_APPROVER_RULES}
""",
    ),
    "reject_application": (
        "Reject a leave application",
        f"""
Rejects the application, and the held days go back to the balance. Put the reason in
`comments`.
{_APPROVER_RULES}
""",
    ),
    "cancel_application": (
        "Cancel a leave application",
        """
Cancels an application. What happens depends on its status:

- `DRAFT` or pending: cancelled at once, and any held days are released.
- `APPROVED`: if cancelling needs approval (from the leave type or an approval flow), it goes
  to `CANCEL_PENDING_L1`. Otherwise it is cancelled and the days are returned.

Other statuses return `400`.
""",
    ),
    "approve_cancellation": (
        "Approve a cancellation",
        f"""
Approves a pending cancellation of approved leave. At the last level, the leave is cancelled
and the days are returned to the balance.
{_APPROVER_RULES}
""",
    ),
    "reject_cancellation": (
        "Reject a cancellation",
        f"""
Turns down the cancellation request (`CANCEL_REJECTED`). The leave stays approved.
{_APPROVER_RULES}
""",
    ),
    # ─── Buckets ─────────────────────────────────────────────────────────────
    "list_buckets": (
        "List balance buckets",
        "Balance buckets are the pools that balances are kept in. Several leave types can "
        "draw from one bucket (for example, Casual and Sick sharing a pool). `is_unlimited` "
        "buckets are never checked for balance.",
    ),
    "create_bucket": (
        "Create a balance bucket",
        "Adds a bucket. Its `code` must be unique (`400`).",
    ),
    "update_bucket": ("Update a balance bucket", "Renames a bucket, or turns it on or off."),
    "delete_bucket": ("Delete a balance bucket", "Removes a bucket."),
    "list_bucket_mappings": (
        "List leave type → bucket mappings",
        "Which bucket each leave type draws its balance from.",
    ),
    "create_or_update_bucket_mapping": (
        "Map a leave type to a bucket",
        "Sets the bucket a leave type draws from, replacing any earlier mapping for that type.",
    ),
    "delete_bucket_mapping": ("Remove a bucket mapping", "Unlinks a leave type from its bucket."),
    # ─── Policy sets ─────────────────────────────────────────────────────────
    "list_policy_sets": (
        "List leave policy sets",
        "A policy set is a named group of entitlement rules (one per bucket), for example "
        "*Staff* or *Workers*. It is assigned to employees, departments or companies.",
    ),
    "create_policy_set": (
        "Create a leave policy set",
        "Creates an empty policy set. Add a rule per bucket with "
        "`POST /v1/leave/policy-sets/{set_id}/bucket-policies`. `is_default` makes it apply to "
        "anyone without an assignment.",
    ),
    "update_policy_set": (
        "Update a leave policy set",
        "Renames a set, or changes its default flag.",
    ),
    "list_bucket_policies_for_set": (
        "List a policy set's rules",
        "The entitlement rule for each bucket in this policy set.",
    ),
    "create_bucket_policy": (
        "Add a bucket rule to a policy set",
        """
Defines how one bucket accrues for employees on this policy set:

- `accrual_type`: `ANNUAL_UPFRONT` (the full year credited at once), `MONTHLY_PRORATE`
  (credited monthly) or `NONE`. The amount is `days_per_year`.
- Carry forward and lapse: `carry_forward_enabled`, `max_carry_forward_days` and
  `lapse_enabled`.
- Encashment: `encashment_enabled` and `max_encashment_days`.
- Eligibility: `probation_eligible`, `min_service_months` and `pro_rate_first_year`.

Only one rule is allowed per bucket in a set (`400`).
""",
    ),
    "update_bucket_policy": ("Update a bucket rule", "Changes the fields you send."),
    "delete_bucket_policy": (
        "Delete a bucket rule",
        "Removes a bucket's rule from its policy set.",
    ),
    "list_policy_assignments": (
        "List leave policy assignments",
        "Which leave policy set applies to which employee, department or company, and when.",
    ),
    "create_policy_assignment": (
        "Assign a leave policy set",
        "Assigns a policy set to one employee (`employment_id`), department (`org_unit_id`) "
        "or company (`legal_entity_id`) from `effective_from`. The most specific assignment "
        "wins, and the default set applies to everyone else.",
    ),
    "delete_policy_assignment": (
        "Remove a leave policy assignment",
        "Deletes the assignment. The employees fall back to the next matching set.",
    ),
}

"""Endpoint docs: Attendance Corrections, HR Policies."""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Attendance corrections ──────────────────────────────────────────────
    "list_corrections": (
        "List correction requests",
        """
Correction requests the caller can see. Without filters, this is everything in their scope:
their own requests, plus their team's or company's when their role covers them.

Filter with `employment_id` and `status` (`PENDING_L1`, `PENDING_L2`, `PENDING_L3`,
`APPROVED`, `REJECTED` or `CANCELLED`). Each request includes its approval history.
""",
    ),
    "create_correction": (
        "Request an attendance correction",
        """
Asks for a day's attendance to be fixed, for example a missed check-out, a wrong punch, or a
late arrival that needs a reason.

- `correction_type` decides which fields matter. `PUNCH_IN`, `PUNCH_OUT`, `MISSED_PUNCH` and
  `REGULARIZE` take `requested_punch_in` and/or `requested_punch_out`. These are ISO
  timestamps, and they must fall within that `work_date`'s work day (`422`).
- If an approval flow or the attendance policy requires approval, the request starts at
  `PENDING_L1`. Otherwise it is `APPROVED` and applied at once.
- Leave out `employment_id` for the caller's own request. Requesting for someone else needs
  `corrections.write` over them.
""",
    ),
    "approve_correction": (
        "Approve a correction",
        """
Approves the request at its current level. At the last level, the correction is applied and
the day is recalculated. Before that, it moves on to the next level (`PENDING_L2`, and so on).

- If an approval flow is assigned, the caller must be that step's approver. Otherwise they
  need `corrections.approve` over the employee.
- You can't review your own request (`403`), and each level needs a different reviewer
  (`409`).
""",
    ),
    "reject_correction": (
        "Reject a correction",
        "Rejects the request at its current level. Attendance is not changed. The same "
        "reviewer rules apply as for approval. Add the reason in `comments`.",
    ),
    "cancel_correction": (
        "Cancel a correction request",
        "Withdraws a request that is still pending. The requester (or HR with "
        "`corrections.write`) can cancel. A request that is already decided returns `400`.",
    ),
    # ─── HR policies ─────────────────────────────────────────────────────────
    "hr_policies_list_templates": (
        "List attendance policy templates",
        "Every active attendance and shift policy: working hours, week pattern, grace "
        "periods, overtime and punch rounding.",
    ),
    "hr_policies_create_template": (
        "Create an attendance policy template",
        """
Defines a shift and attendance policy.

- `expected_start_time` and `expected_end_time` are local times in `timezone`.
- `work_days` has seven characters, Monday to Sunday, where `1` is a working day. For
  example, `1111100` means Monday to Friday.
- `saturday_pattern` handles alternate Saturdays (`SECOND_OFF`, `SECOND_FOURTH_OFF`, and
  so on).
- `grace_late_minutes` and `grace_early_departure_minutes` allow lateness before it counts.
- `half_day_threshold_pct` is the share of the standard day below which a day is `HALF_DAY`.
- Overtime: `ot_enabled`, `ot_qualifying_minutes` (the minimum extra time that counts),
  `ot_rate` and `ot_daily_cap_minutes`.
- `off_day_work` decides whether work on an off day becomes `OVERTIME` or `COMP_OFF`.
- `correction_requires_approval` and `correction_approval_levels` apply to correction
  requests when no approval flow is assigned.
- `is_default: true` makes this the tenant default (the previous default is unset).
""",
    ),
    "get_template": (
        "Get an attendance policy template",
        "One policy template with every setting.",
    ),
    "update_template": (
        "Update an attendance policy template",
        "Changes the fields you send. Every employee on this policy is affected. Needs "
        "`policy.write` across all companies.",
    ),
    "archive_template": (
        "Archive an attendance policy template",
        "Archives the template, which removes it from the list. Needs `policy.write` across "
        "all companies.",
    ),
    "list_assignments": (
        "List policy assignments",
        "Which policy applies to which employee, department or company, and when. Filter by "
        "`employment_id`, `org_unit_id` or `legal_entity_id`. Needs `policy.read`.",
    ),
    "assign_policy": (
        "Assign a policy",
        """
Assigns a policy template to **one** of these: an employee (`employment_id`), a department
(`org_unit_id`), or a company (`legal_entity_id`). It applies from `effective_from` until
`effective_to` (open-ended if left out).

The `*_override` fields change single settings for this assignment only, for example a longer
grace period for one employee.

**The most specific policy wins:** employee, then department (going up the department
tree), then company, then the tenant default.
""",
    ),
    "remove_assignment": (
        "Remove a policy assignment",
        "Deletes an assignment. The employee falls back to the next policy in line.",
    ),
    "get_effective_policy": (
        "Get an employee's effective policy",
        "The policy that actually applies to an employee on `work_date` (default today), with "
        "overrides included. Use this to explain an attendance result.",
    ),
}

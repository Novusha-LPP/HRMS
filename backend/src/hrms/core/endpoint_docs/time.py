"""Endpoint docs: Time & Attendance, Holiday calendars."""

_ACTING_EMPLOYEE = """
Leave `employment_id` out to act on the caller's own record. Viewing someone else needs them
to be in the caller's scope.
"""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Punches and attendance ──────────────────────────────────────────────
    "create_punch": (
        "Record a punch",
        """
Records a live punch, timestamped with the **server's** clock when the request arrives.

- `punch_type` must follow the sequence `IN` → (`BREAK_START` → `BREAK_END`)* → `OUT`.
  Anything else returns `409`. Use an attendance correction to fill in a missing event.
- Only `source` `WEB` or `MOBILE` is accepted, and `punched_at` must be left out. Backdated
  punches and biometric-device imports are refused (`422`). They go through corrections, or
  an HR edit in the attendance register.
- A check-out after midnight closes the session that started the day before, up to 24 hours
  after check-in. After 24 hours, the open day becomes `MISSED_PUNCH` and needs a correction.
- **`409 LONG_DAY_CONFIRM`:** a check-out after a very long open session. Usually someone
  forgot to check out. To record it anyway, resend with `confirm_long_day: true`. The day then
  goes to HR for review.

To punch for another employee, pass `employment-id`. That needs `time.write` over them.
""",
    ),
    "today_status": (
        "Today's attendance status",
        f"""
An employee's punches and status for today (or for `work_date`), as the punch clock shows it.
"Today" follows the employee's policy timezone and shift work date. A missed check-out
on a previous work date does not carry into today's check-in status. Overnight shifts
remain on their assigned work date until the shift's work-date boundary.
{_ACTING_EMPLOYEE}
""",
    ),
    "list_attendance_days": (
        "List attendance days",
        f"""
One row per work date between `from_date` and `to_date` (inclusive): status, first in, last
out, worked and overtime minutes, lateness and review flags.

`status` is one of `PRESENT`, `ABSENT`, `HALF_DAY`, `LATE`, `EARLY_DEPARTURE`, `ON_LEAVE`,
`HOLIDAY`, `WEEKEND`, `PENDING` (checked in, not yet out), `MISSED_PUNCH` (no check-out within
24 hours) or `OFF_DAY_WORKED`.
{_ACTING_EMPLOYEE}
""",
    ),
    "list_holidays": (
        "List holidays",
        "Holidays in the tenant's holiday list, optionally for one `year`. Each one names the "
        "holiday calendars that include it.",
    ),
    "create_holiday": (
        "Add a holiday (legacy)",
        "Adds a holiday directly. New setups should use the holiday list and calendars "
        "(`/v1/time/holiday-calendars`), which control who observes each holiday.",
    ),
    "delete_holiday": (
        "Delete a holiday (legacy)",
        "Removes a holiday added with the endpoint above.",
    ),
    "list_pending_overtime": (
        "List overtime waiting for review",
        "Attendance days in the caller's scope with overtime that hasn't been approved or "
        "rejected yet. Optionally limit to `from_date`–`to_date`.",
    ),
    "review_overtime": (
        "Approve or reject overtime",
        """
Records a decision (`APPROVED` or `REJECTED`) on one day's overtime. Only approved overtime
counts.

- When an approval flow covers overtime, the caller must be the current approver in that flow.
  Otherwise they need `corrections.approve` over the employee.
- You can't approve your own overtime (`400`).
- A day that was already decided returns `400`.
""",
    ),
    "review_attendance_day": (
        "Accept a flagged day",
        "Marks a day that was flagged for review (for example an unusually long day) as checked, "
        "with the punches unchanged. You can't review your own attendance. A day with nothing "
        "to review, or one already reviewed, returns `400`.",
    ),
    "daily_analysis": (
        "Daily attendance analysis",
        """
Everyone in the caller's scope for one `work_date` (default today): status, first in and last
out, hours, lateness. Also returns totals overall and by department.

**Paging works on a snapshot.** The first call (no `snapshot_id`) calculates the day and
returns a `snapshot_id`. Pass it with `offset` for the following pages, so every page comes
from the same data. A snapshot lasts about 5 minutes. After that, or if the caller's access
changes, you get `409`, so start again from the first page.

**Filters:** `department` (exact name), `search` (name or employee number), and `status`. The
status can be `PRESENT`, `LATE`, `NEEDS_REVIEW`, or any attendance status.

Returns `429` when another report is still being generated, so retry shortly.
""",
    ),
    "daily_analysis_export": (
        "Export the daily analysis (CSV)",
        "Downloads a snapshot from `GET /v1/time/daily-analysis` as a CSV file, with the same "
        "filters. Needs the `snapshot_id` from that call.",
    ),
    # ─── Attendance register ─────────────────────────────────────────────────
    "find_employees": (
        "Find an employee",
        "Searches employees in the caller's scope by name or employee number, for opening "
        "their attendance register.",
    ),
    "register_filters": (
        "Register companies and departments",
        "The companies and departments of the people the caller can see in the attendance "
        "register, to populate its filters. Needs `people.read`; results follow the caller's "
        "scope.",
    ),
    "employee_register": (
        "Get an employee's attendance register",
        "Day-by-day attendance for one employee, with every punch, its source, and any "
        "corrections. The range can be at most 62 days (`422` otherwise).",
    ),
    "edit_day": (
        "Replace a day's punches (HR)",
        """
Replaces every punch on one day with the list you send, and recalculates the day. No approval
step is involved.

- Each `punched_at` must include a time-zone offset, for example `2026-09-27T09:00:00+05:30`.
- `reason` is required. The edit is recorded as a correction of type `DIRECT_EDIT`.
- You can't edit your own attendance (`403`), a future day, or a day the employee wasn't
  employed (`422`).
- Sending the same punches again returns `400`.
""",
    ),
    # ─── Marked attendance ───────────────────────────────────────────────────
    "marking_day": (
        "A day's marked attendance",
        """
Everyone in the attendance groups the caller can see (guards, drivers, cleaners…), employed
on `work_date`, with that day's state. A group is visible if the caller was given **VIEW** or
**MARK** on it, or holds `attendance.groups.manage` (every group, for people in their scope).

- `PRESENT` / `ABSENT`: marked; with times, the status the times give (`LATE`, `HALF_DAY`…);
- `OFF_DAY_WORKED`: present on a weekly off or holiday;
- `NOT_MARKED`: a working day nobody has marked yet (never counted as an absence);
- `ON_LEAVE`, `HOLIDAY`, `WEEKEND`, `UPCOMING`, or a punched day's own status.

`access` and `can_mark` / `blocked_reason` say what the caller may do with each row;
`punch_in` / `punch_out` / `worked_minutes` show times a marker entered, `mark` the latest mark
(who, when, from where, remark). Filter with `group_id` and `legal_entity_id`.
""",
    ),
    "mark_day": (
        "Mark a day for many people",
        """
Marks `work_date` `PRESENT` or `ABSENT` for each person in `marks`, or clears the mark with
`status: null` (the day goes back to `NOT_MARKED`). Needs **MARK** on each person's group.

Optional `punch_in` / `punch_out` (`HH:MM` on the person's own clock, with `PRESENT`) are kept as
punches with source `MARKED`, and the day is worked out from them like any punched day: hours,
late, half day, overtime. An out time not after the in time is the next morning (night shift).
Changing or clearing a mark voids the earlier times (kept in the history).

The whole request is checked first. If any row breaks a rule, **nothing** is saved and the `422`
names each refused person: not in a group the caller can mark, their own attendance, a future or
locked day, a time later than now, a day with their own punches or on approved leave, or
`ABSENT` on a day off. A row's `remark`, else the top-level `remark`, is kept with the mark.
""",
    ),
    "marking_leave_types": (
        "Leave types a marker can record",
        "The company's active leave types, for recording leave with "
        "`POST /v1/time/marking/leave`. Needs **MARK** on at least one group.",
    ),
    "record_leave": (
        "Record leave from one date to another",
        """
Records leave for someone in a group the caller can **MARK**, as an **approved** leave
application with the caller as approver. It meets every rule an application does except advance
notice: active type, length, document, overlap (`409`) and balance
(`409 Insufficient leave balance`; use a leave-without-pay type then).

An `ABSENT` mark on those days is cleared, and its history says why. A `PRESENT` mark, a day with
the person's own punches, or a locked day refuses the leave (`409`). Your own leave is refused
(`403`).
""",
    ),
    "list_groups": (
        "Attendance groups you can see",
        "Groups of people whose attendance is marked (guards, drivers, cleaners…) that the "
        "caller can VIEW or MARK, with today's member count. With `attendance.groups.manage`, "
        "every group.",
    ),
    "create_group": (
        "Create an attendance group",
        "Needs `attendance.groups.manage`. Names are unique (ignoring case) among active groups "
        "(`409`). Set `legal_entity_id` to allow only that company's people in it.",
    ),
    "update_group": (
        "Rename or describe an attendance group",
        "Needs `attendance.groups.manage`. Restricting it to a company is refused while members "
        "from another company are still in it (`409`).",
    ),
    "archive_group": (
        "Retire an attendance group",
        "Needs `attendance.groups.manage`. Only a group with nobody in it can be retired (`409`). "
        "Its history stays.",
    ),
    "list_members": (
        "Who is in an attendance group on a day",
        "The people in the group on `on` (default today) and since when. Needs VIEW or MARK on "
        "the group, or `attendance.groups.manage`.",
    ),
    "add_members": (
        "Add people to an attendance group",
        """
Adds people from `effective_from`: from that day their attendance is marked, not punched. Needs
`attendance.groups.manage`, over people in the caller's scope.

A person is in one group at a time: someone already in another group then is refused (`409`,
"take them out first"). Nobody is added if any row is refused. Adding someone already in this
group changes nothing.
""",
    ),
    "remove_member": (
        "Take someone out of an attendance group",
        "Ends the membership after `last_day` (default today); from the next day their attendance "
        "is punched again, or they can join another group. Days before stay marked. Needs "
        "`attendance.groups.manage`.",
    ),
    "list_access": (
        "Who may view or mark a group",
        "The people given **VIEW** (see the daily sheet) or **MARK** (also mark days and record "
        "leave) on this group. Needs `attendance.groups.manage`.",
    ),
    "grant_access": (
        "Let someone view or mark a group",
        """
Gives a login **VIEW** or **MARK** on the group, or changes it. The grant is the whole permission
for that group: the person needs no HR role, and it isn't narrowed by their role's scope, so a
supervisor can keep the guards' sheet with an ordinary employee login. Needs
`attendance.groups.manage`.
""",
    ),
    "revoke_access": (
        "Withdraw someone's access to a group",
        "Takes effect at once. Marks they already made stay, with their name. Needs "
        "`attendance.groups.manage`.",
    ),
    # ─── Holiday calendars ───────────────────────────────────────────────────
    "coverage": (
        "Holiday calendar coverage",
        "How many people follow each calendar on date `on` (default today). This includes a "
        '"No calendar" row for people who aren\'t covered.',
    ),
    "list_library": (
        "List the holiday list",
        """
The tenant's master list of holidays for a `year`. A holiday is stored once and linked from
each calendar that observes it, so renaming it renames it everywhere.
""",
    ),
    "add_library_holiday": (
        "Add a holiday to the list",
        "Adds a dated holiday to the master list. Only one holiday is allowed per date (`409`).",
    ),
    "update_library_holiday": (
        "Update a holiday",
        "Renames or moves a holiday. Every calendar that includes it changes too. It must stay "
        "in the same year (`422`) and can't clash with another holiday's date (`409`).",
    ),
    "delete_library_holiday": (
        "Delete a holiday",
        "Removes the holiday from the list **and from every calendar** that includes it.",
    ),
    "list_calendars": (
        "List holiday calendars",
        "Calendars with their days and assignments, optionally for one `year`.",
    ),
    "create_calendar": (
        "Create a holiday calendar",
        """
Creates a calendar for one `year`.

- `holiday_ids`: holidays from the list to include. They must be in that year.
- `copy_from`: a calendar ID whose days are copied.
- `assign_company: true`: makes this the company-wide calendar straight away.
""",
    ),
    "rename_calendar": ("Rename a calendar", "Changes a calendar's name."),
    "archive_calendar": (
        "Archive a calendar",
        "Archives the calendar and ends its assignments. People fall back to the next "
        "matching calendar.",
    ),
    "add_day": (
        "Add a holiday to a calendar",
        """
Adds one day. Either give `holiday_id` from the list, or give `holiday_date` and `name` to
create the holiday in the list at the same time. Set `is_optional` for a restricted (optional)
holiday. The date must be in the calendar's year.
""",
    ),
    "update_day": (
        "Update a calendar day",
        "Changes whether a day is optional, or its name.",
    ),
    "remove_day": (
        "Remove a holiday from a calendar",
        "Removes the day from this calendar only. The holiday stays in the list.",
    ),
    "set_days": (
        "Set a calendar's holidays",
        "Replaces the calendar's days with exactly this selection from the holiday list, each "
        "marked optional or not.",
    ),
    "assign_calendar": (
        "Assign a calendar",
        """
Makes a calendar apply to the whole `COMPANY`, a `LEGAL_ENTITY`, a `DEPARTMENT` (including
its sub-units), or one `EMPLOYEE`. Give `target_id` for every target except `COMPANY`.

**The most specific assignment wins:** employee, then department, then legal entity, then
company.

The assignment runs from `effective_from` (default 1 January of the calendar's year) to
`effective_to` (open-ended by default). If another calendar already covers the target in that
period, you get `409 CALENDAR_ASSIGNED`. Resend with `replace: true` to end the old assignment
the day before.
""",
    ),
    "unassign_calendar": (
        "Remove a calendar assignment",
        "Deletes one assignment. People it covered fall back to the next matching calendar.",
    ),
}

# Marked attendance and attendance groups

Some people don't punch: guards, drivers, cleaners. Their days are **marked present or absent**
by someone else, with **in and out times if they're known**, and their leave is recorded as a
**from–to range**. Everyone else keeps punching as before.

## Setting it up (Settings → Attendance groups, needs `attendance.groups.manage`)
1. **New group**: for example Guards, Drivers, Cleaners. Optionally limit it to one company.
2. **Add people** from a date. From that day their attendance is marked, not punched. Their
   policy still sets their shift, holidays and weekly offs. A person is in one group at a time:
   **Take out** with a last day, then add them to the other group. Past days keep their meaning.
3. **Who can view or mark**: give a login **View** (see the daily sheet) or **Mark** (also mark
   days and record leave) on this group. A supervisor needs no HR role. A guard supervisor can
   have Mark on Guards only, and View on Drivers. HR managers can always view and mark.

## Marking a day (Workforce → Mark attendance)
- The sheet lists everyone in the groups you can see for the chosen day. Rows of groups you can
  only view are read-only.
- Set each person **Present** or **Absent**, or **Clear**. **Mark the rest present** fills in
  everyone not yet marked. Save once, with an optional remark.
- **Add times** on a present row: In, and optionally Out. Times count like punches: hours, late,
  half day and overtime follow the person's policy. An out time earlier than the in time is the
  next morning (night shift). Times can't be later than now.
- A save is checked as a whole. If any row breaks a rule, nothing is saved and the message names
  each person and why.

| Rule | Why |
|---|---|
| Nobody marks their own attendance | Same as the attendance register |
| Only today or earlier, only while the person was employed and in the group | A mark records what happened |
| A locked (closed) day can't be changed | Payroll has used it |
| A day with the person's own punches can't be marked | It is computed from them; correct it in the register |
| A day on approved leave can't be marked | The leave says what the day was |
| Absent on a weekly off or holiday is refused; present is off-day work | Absent means nothing on a day off |
| An out time equal to the in time is refused | It would be a 24-hour shift |
| Times overlapping the shift of the day before or after are refused | Someone can't be on two shifts at once (night shifts) |
| Leave approved while someone is marking blocks the save | The sheet was out of date; reload |

A working day nobody marked shows **Not marked**, never Absent, in the register, the daily
analysis and the attendance report (which counts `not_marked_days` separately).

## Recording leave
**Leave** on a row: leave type, from, to, reason. It becomes an **approved leave application**
through the leave engine. The type, length, overlap and **balance** rules apply, and if there is
too little balance you pick an unpaid type. Advance notice does not apply, because the leave is
being recorded, not requested. An absent mark on those days is cleared, with the reason kept. A
present mark must be cleared first. Needs Mark on the person's group **on every day of the
range**: days they spent outside it (or in a group you can't mark) are named and refused.

## History and audit
Every change is kept in `attendance_marks` (append-only): status, any times, who, when, the
remark, and whether it came from a person or a connected app. Times are stored as punches with
source `MARKED`, apart from the person's own punches. When a mark changes, the old times are
voided, never deleted. The day itself reads like any other day, so payroll, reports and
dashboards need nothing special.

## Permissions
| Who | What |
|---|---|
| `attendance.groups.manage` (HR managers) | Create and change groups, members and access; view and mark every group, for the people in their scope |
| Given **Mark** on a group | View and mark that group's daily sheet, record leave for its people |
| Given **View** on a group | See that group's daily sheet |

When a group is retired, access given on it ends. HR can still correct its members' past days on
the marking sheet.

`/v1/auth/me` adds `attendance.view` / `attendance.mark` to a user's permissions when they hold
group access, so the app shows them the sheet.

## API
`/v1/time/attendance-groups` (groups, members, access) and `/v1/time/marking` (day sheet,
marks, leave types, leave). The reference text is in the API docs (`core/endpoint_docs/time.py`).
A connected app can mark through the same calls; its marks are recorded with source
`INTEGRATION`.

## Deploying
Migration `0074` adds `attendance_groups`, `attendance_group_members`, `attendance_group_access`
and `attendance_marks`, and allows the `MARKED` punch source. Nothing changes for anyone until
HR creates a group and adds people.

## Not built yet
- A pull from the transport platform's attendance API. The `INTEGRATION` source is ready for it.
- Importing the old driver attendance (`exim.attendances.json`). The drivers must be HRMS
  employees first.
- Cancelling recorded leave from the marking page. HR cancels it from Leave.
- Half-day marks without times. With times, half days come from the hours.
- Rotating shift rosters for guards. A fixed night policy works today.

## Importing the EXIM drivers (2026-10-28)
The 56 EXIM drivers have only a username and password in the export. Two scripts, both dry-run by
default and safe to repeat:

1. `migrate_tenants.py --tenant suraj --suraj-tenant suraj-group --drivers-entity "SR Container Carriers" --allow-partial`
   creates them as employees of that company (name from the username, joined when their account
   was made, their old password kept). A driver whose old login is active is employed. One whose
   login is switched off has left, so they don't show among working people: on the day after
   their last marked day (all their marked days stay theirs), or the day after joining if never
   marked. Left drivers appear only under Employees → Inactive.
2. `import_exim_drivers_group.py --tenant suraj-group --apply` creates the **Drivers** group, puts
   each driver in it for their employment, gives drivers without a policy of their own
   **Drivers (7-day week)** (a copy of the default policy working all week: in the old data they
   worked Sundays as much as weekdays), and imports `exim.attendances.json` as marks with the
   original marker and time. Old "leave" had no application, so it becomes absent with a note.
   Absent on a holiday is skipped.

Rehearsed on a copy of the local database and applied locally: 56 drivers (36 employed, 20 left),
5,394 days (4,002 present, 1,215 absent, 177 leave as absent), 35 holiday absences skipped; a
second run adds nothing. Who can mark the Drivers group is set by the Admin under
Attendance groups → Drivers → Who can view or mark.

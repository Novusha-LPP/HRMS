# UI 3 · Status vocabulary

Statuses use the requirements' wording exactly (§4, §12, §21) and always pair a word with a tone and an icon. `HRMS.STATUS_TONES` is the single map; screens call `HRMS.badge(label)`.

| Tone | Icon | Means | Statuses |
|---|---|---|---|
| success | check | Finished, positive outcome | Active, Confirmed, Selected, Joined, Approved, Resolved, Completed, Present, Verified, Cleared |
| info | ring | Under way; nothing needed from the viewer yet | Probation, Open, Screening, Interview, Offer, New, In Progress, Planned, Submitted, Half Day, On Leave, Overtime, Work From Home, Official Duty, Uploaded |
| pending | clock | Waiting on someone, or needs attention soon | Pending, Waiting for Employee, On Notice, Notice, Clearance, F&F Pending, Late, Early Leaving, Missing Punch, Pending Verification |
| danger | cross | Ended badly or is broken | Rejected, Absent, Expired |
| overdue | warning | Past its due date; solid `danger` fill | Overdue |
| exception | flag | Approved deviation or a deliberate hold | Exception, Hold |
| neutral | dash | Inactive, closed or not relevant | Draft, Exited, Closed, Cancelled, Not Applicable, Holiday, Weekly Off, Replaced |

## Status categories behind the labels

Each status code maps to a platform category: *not started, open, waiting, done-positive, done-negative, cancelled, exception*. Dashboards, the Action Centre and cross-module reports count by category, which is why tenants can rename a label but not move it to another tone.

## Rules

- **Overdue is computed, not chosen.** An item becomes Overdue when its due date passes while its category is open or waiting. Nobody sets it by hand.
- **Due soon** (inside the tenant's first reminder offset) shows as `pending-ink` text on the due date, not as a separate status.
- **Employment state and service stage are two badges** (for example "On Notice" and "Probation"), because they are two fields (Architecture 2).
- **Never colour-only.** Badges keep their word and icon; rows and cards are never tinted by status.

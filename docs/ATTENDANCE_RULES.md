# Attendance rules — quick guide

Example shift: **09:30–18:30** (9 h), break 60 min → **standard day 8 h**. Grace **15 min**. Half day = **under 4 h**.
Overtime counts only **after the full shift** (after 9 h worked).

## How a day is calculated

- **Total** = first check-in → last check-out.
- **Away** = time checked out in between + recorded breaks.
- **Worked** = Total − Away. Nothing is deducted automatically.
- A break **never ended** counts only up to the policy break (60 min); the rest is worked, and HR reviews the day.

## Status (first match wins)

1. **Worked on off day** — checked in on a weekly off or holiday (no late or early marks).
2. **Absent** — 0 worked.
3. **Half day** — worked under 4 h.
4. **Late** — first check-in after 09:45.
5. **Early departure** — last check-out before 18:15.
6. **Present** — otherwise.

Late, early, half days and off-day work all **count as present** in totals. Late minutes = minutes after 09:30 − 15.

## Cases

| Case | Punches | Worked | Result |
|---|---|---:|---|
| Normal (no break) | 09:30–18:30 | 9 h | Present, no OT |
| Lunch by checking out | 09:30–13:30, 14:30–18:30 | 8 h | Present |
| Recorded break | 09:30–18:30, break 13:00–13:45 | 8 h 15 m | Present |
| Field visits | 4 sessions, 1 h 45 m away | 8 h 2 m | Present |
| Inside grace | 09:44–18:20 | 8 h 36 m | Present |
| Late | 10:05–18:30 | 8 h 25 m | Late, 20 min |
| Left early | 09:30–17:30 | 8 h | Early departure, 45 min |
| Late + early | 10:00–17:00 | 7 h | Late (both recorded) |
| Short day | 09:30–13:00 | 3 h 30 m | Half day |
| Exactly 4 h | 09:30–13:30 | 4 h | Early departure |
| Came very early | 03:00–11:00 | 8 h | Early departure |
| Same minute | 09:30–09:30 | 0 | Absent |
| Below OT threshold | 09:30–19:05 | 9 h 35 m | 35 min extra, below 40 → no OT |
| Overtime | 09:30–19:10 | 9 h 40 m | 40 min OT, needs approval |
| Still at work | 09:30, no out yet | 0 so far | Present (checked in) |
| Past midnight | Fri 09:30 → Sat 01:15 | 15 h 45 m | Friday: Present, 6 h 45 m OT |
| Forgot to check out | 09:30, no out for 24 h | 0 | **Missed punch** |
| No punches | — | — | Absent / Weekend / Holiday / On leave |

### More cases (all tested)

| Case | Punches | Worked | Result |
|---|---|---:|---|
| Grace edge | in 09:45 / 09:46 | — | on time / 1 min late (seconds ignored) |
| Grace edge | out 18:15 / 18:14 | — | on time / 1 min early |
| Back from lunch, still at work | 09:30–13:00, in 14:00 | 3 h 30 m so far | Present (not early) |
| Break never ended | in 09:30, break 13:00, out 18:30 | 8 h | Present — break counted as 60 min, **HR review** |
| Two breaks | 15 m + 45 m recorded | 8 h | Present |
| Came early | 08:00–18:30 | 10 h 30 m | Present, **90 min OT** (early time counts) |
| Came late, stayed late | 10:30–19:30 | 9 h | Late 45 min, no OT |
| Late and short | 12:00–15:00 | 3 h | Half day (late/early still recorded) |
| Lunch out, stayed late | 09:30–13:30, 14:30–19:40 | 9 h 10 m | Present, 10 min extra → no OT |
| Exactly 16 h | 09:30 → 01:30 | 16 h | Present, 7 h OT |
| Over 16 h | 09:30 → 02:00 | 16 h 30 m | Present, **HR review** — OT held until accepted |
| Late night, then new day | 09:30 → 01:00, again 02:00–05:00 | 15 h 30 m + 3 h | Two separate days |
| Night shift 22:00–06:00 | 21:55 → 06:05 | 8 h 10 m | Present |
| Night shift, came after midnight | 00:30 → 06:00 | 5 h 30 m | Late 135 min |
| Night shift, stayed late | 22:00 → 07:00 | 9 h | 60 min OT |
| Rounding 15 min, nearest | 09:37–18:38 → 09:30–18:45 | 9 h 15 m | Present |
| Rounding 15 min, up | in 09:46 → 10:00 | — | Late 15 min |
| OT cap 60 | 09:30–21:30 | 12 h | 60 min OT (capped) |
| Wrong taps | double break, check-out twice, out before in | — | Refused, numbers unchanged |
| Two taps at the same second | IN + IN | — | Only one recorded |
| Correction | add missing out, fix late in | — | Day recalculates after approval |
| Locked period | punch or correction | — | Refused |

## Overtime

- OT = worked time **beyond the full shift** (09:30–18:30 → after 9 h). Working the whole shift without a break is not OT.
  Time before the shift counts too (08:00–18:30 → 90 min).
- **OT policy defined** (overtime enabled): its rules apply — e.g. counts only once **40 min or more** extra, daily cap
  if set → status **Pending** → approved in **Approvals** → goes to **payroll** (later).
- **No OT policy** (overtime off): the plain extra time is still calculated and shown as **Extra time (not paid)** —
  never sent for approval, never to payroll.

| Punches | OT policy (40 min threshold) | No OT policy |
|---|---|---|
| 09:30–18:30 | none | none |
| 09:30–19:05 (35 min extra) | none | 35 min shown only |
| 09:30–19:10 (40 min extra) | 40 min, pending approval | 40 min shown only |

## Weekly offs and holidays

A weekly off (from the policy's work days and Saturday pattern) or a company holiday is an **off day**. Optional
holidays and other companies' holidays are not. Work on an off day shows **Worked on off day**, with no late or early
marks. The policy decides what it earns:

| Policy setting | Sat 10:00–14:00 (4 h) | Sat 09:30–18:30 (9 h) |
|---|---|---|
| **Counts as overtime** (OT on, 40 min) | 4 h OT, pending approval | 9 h OT (cap applies) |
| **Counts as overtime** (OT off) | 4 h shown only | 9 h shown only |
| **Earns comp-off** | ½ day comp-off | 1 day comp-off |

- Comp-off: a full standard day (8 h) earns **1 day**, at least half of it (4 h) earns **½ day**, less earns nothing.
  It is added to the leave balance automatically; a later correction adjusts it. A comp-off HR granted by hand is
  never changed.

## Setting up holidays

**Policies → Leave policies → Holiday Calendar**, in three steps:

1. **Holiday list** — add every holiday of the year once (date + name). On the list alone a holiday is nobody's
   day off.
2. **Calendars** — create named calendars (e.g. *HO*, *Operations*) and tick which holidays each includes. A holiday
   can be on several calendars; mark it *optional* on a calendar where people may work.
3. **Who gets which** — give each calendar to the **whole company**, a **company entity** or a **department**
   (sub-departments included).

Each person follows one calendar: the most specific wins — person › department › company entity › whole company.
Deleting a holiday from the list removes it from every calendar.

| Live company | Calendar | Who |
|---|---|---|
| Suraj Group | HO Holiday (10 days) | whole company |
| Suraj Group | Operations Holiday (19 days) | Operations dept of Suraj Forwarders & Shipping Agencies, + 3 people |
| RABS | Holiday (10 days) | whole company |

Mapped from `exim.holidaypolicies.json` on 6 Oct 2026 (`backend/scripts/map_holiday_calendars.py`).

## Days HR must review

A day is flagged **Needs review** when:

- a **break was never ended** (counted only up to the policy break), or
- it runs **over 16 hours** from first check-in to last check-out.

Until HR acts, its **overtime and comp-off are held**. HR either **corrects** the punches (the flag clears itself) or
clicks **Accept as recorded** in **Daily Analysis → Needs review** (then OT goes for approval / comp-off is credited).

## Past midnight and missed punches

- A check-out **within 24 h** of the check-in closes that day, even after midnight.
- If the check-out would make the day **over 16 h**, the app warns first: *"You checked in at 09:30 on 05 Oct … this
  records a 23-hour day, which HR will review."* The employee can cancel and ask HR to correct the time, or confirm.
- **After 24 h** the check-out is refused → the day becomes **Missed punch** → HR corrects it.

## Blocked by the clock

Double check-in · check-out without check-in · break end without start · double check-out.

## Corrections

Fix check-in, check-out (up to 24 h after check-in), both, or mark present/absent. Approved in **Approvals**; the day
recalculates at once. Locked periods can't be changed.

## Attendance register (HR)

**Workforce → Attendance register** (also the **Attendance** tab of an employee's profile, and *Edit this day* /
*Open attendance register* in Daily Analysis):

- Pick an employee → their month **day by day**: status, check-in/out, worked, away, late/early, overtime or comp-off,
  review flags, and every punch (click a day).
- **Edit** (HR with corrections rights) replaces the day's punches directly — check in/out, breaks, next-day
  check-out, *Shift times*, or *Clear* to mark absent. A **reason is required**; it **applies at once**, with no approval.
- The old punches are kept (voided, not deleted). The change appears in the employee's **Corrections** as *Edited by
  HR*, with the reason.
- If the edited day is still over 16 h or has a break never ended, it counts as **reviewed by HR**, so its overtime /
  comp-off goes ahead.
- Not allowed: editing **your own** attendance (request a correction instead), a **future** day, or a **locked**
  period. Punches must be in order, within 24 h of the first check-in.

## Reports

- Every screen shows the same numbers.
- **Present** counts any day with a check-in.
- **Late** counts any day with late minutes.
- In **Reports → Attendance**, filter **Present + Late + Early departure + Half day + Missed punch + Worked on off
  day** to see everyone who came in.

## Live companies

| | Suraj Group | RABS |
|---|---|---|
| OT rule | **none** — set overtime **off** so extra time shows as "not paid" | on; minimum extra set by RABS HR (1 h or 30 min) |
| Off-day work | choose in the policy (default: overtime) | choose in the policy (default: overtime) |

Days recorded before 5 Oct 2026 are not recalculated automatically.

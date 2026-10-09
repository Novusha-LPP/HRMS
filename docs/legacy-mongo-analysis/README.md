# Legacy MongoDB export analysis

Scope: `exim.attendancepunches.json`, `exim.weekoffpolicies.json`, and `exim.holidaypolicies.json`. This is an audit of exported documents, not the live MongoDB database. The original exports were not changed. Company and employee names were not resolved from other collections.

## Inventory and storage model

| Collection | Documents | Purpose |
|---|---:|---|
| attendancepunches | 33,147 | Individual IN/OUT events referencing employee and company IDs |
| weekoffpolicies | 4 | Embedded recurring weekly/monthly day rules |
| holidaypolicies | 3 | Embedded holiday calendars for 2026; 39 holiday entries total |

The files are JSON arrays using MongoDB Extended JSON (`$oid`, `$date`, and one nested `$numberLong` date). `_id` values are unique within all three exports. All punch records contain the same 15 top-level fields, with no top-level null values. Policies include creation/update metadata and `__v`, a pattern consistent with Mongoose-managed documents; the originating code was not inspected.

Punch documents link to employees and companies through ObjectIds, but contain no explicit shift, schedule, policy assignment, timezone, device event ID, or derived attendance result. Week-off rules and holiday entries are embedded arrays. There are no explicit relationships between punches and policy IDs in these three collections.

## Attendance coverage

- 163 distinct employee IDs, 11 company IDs, and 16,788 employee/company/calendar-day groups.
- UTC timestamps span April 1, 2026 at 12:50:05.765 through October 6, 2026 at 06:05:28.319. In India time, the final event is October 6 at 11:35:28.319; that day is incomplete.
- 17,572 IN events and 15,575 OUT events.
- Methods: web 22,756; mobile 9,302; auto 1,089. Every auto event is OUT.
- All 33,147 events are marked valid, all validation-error arrays are empty, and none are marked regularized. These flags do not establish clean attendance, given the anomalies below.
- 23 employee IDs appear under more than one company. This may reflect transfers or shared employment; the exports cannot establish which.

| Month | Punch events |
|---|---:|
| April 2026 | 5,592 |
| May 2026 | 4,991 |
| June 2026 | 5,171 |
| July 2026 | 5,741 |
| August 2026 | 5,501 |
| September 2026 | 5,367 |
| October 2026, partial | 784 |

## Findings affecting attendance calculations

### Repeated events

There are 31 groups with identical company, employee, timestamp, and punch type, contributing **1,066 excess events**. IDs are distinct, so this is repeated event content rather than repeated document IDs.

The largest group repeats one event 693 times. The same employee/company has 694 punches on April 2 (one web event and 693 auto events, only two distinct timestamps), and 349 punches on April 3 (three web and 346 auto events, only four distinct timestamps). This strongly suggests an auto-checkout retry/idempotency problem, but the producer code and logs are needed to confirm the cause. Preserve the raw records and identify a canonical event set before aggregating attendance.

### Incomplete or unexpected punch sequences

Of 16,788 day groups, 12,994 contain exactly `IN OUT`; 2,922 contain only one event, including 2,822 before the final export day. There are 2,858 IN-only groups and 64 OUT-only groups. Another 213 groups contain `OUT IN`, and some contain repeated IN or OUT events. Multiple legitimate work sessions also occur, including 250 `IN OUT IN OUT` groups.

These are candidates for investigation, not confirmed absences or invalid days. Overnight shifts, missed punches, export boundaries, company transfers, and auto-checkout rules can affect pairing. Pairing by calendar day alone cannot establish payable hours. The IN-minus-OUT total is also not a reliable missing-checkout count because duplicates and multiple sessions distort it.

### Mixed calendar-date storage

`punch_date` uses three conventions:

- 30,683 records: UTC midnight.
- 2,462 records: 18:30 UTC, representing midnight in India on the following calendar day.
- Two records: non-midnight values, 04:14 UTC and 02:31 UTC.

Consequently, taking the UTC date from `punch_date` disagrees with `punch_date_str` in 2,462 records. This is mostly a representation inconsistency rather than evidence of a wrong business date. Taking the UTC date from `punch_time` disagrees in 171 records; converting `punch_time` to India time agrees with `punch_date_str` in **every record**.

A migration should store punch instants in UTC and preserve the business date separately. India-time calendar dates are supported by this export, but overnight shift work-date rules still need to be recovered from the old application. Do not blindly convert every `punch_date` timestamp to local time without accounting for its mixed convention.

## Week-off policies

All four policies are active, fixed, and apply to all teams according to their embedded applicability settings.

| Policy | Company scope | Encoded rules |
|---|---|---|
| Operation Weekoff | Missing | Day 0 / week 0; day 6 / week 2 |
| HO Weekoff | `69cd1e3b50e6c73acc73a918` | Day 0 / week 0; day 6 / week 2 |
| NOVUSHA WEEKOFF POLICY | Missing | Day 0 / week 0; day 6 / weeks 2 and 4 |
| General Week Off | `69cd1e3b50e6c73acc73a926` | Day 0 / week 0 |

All rules specify `full_day`. If the old application uses JavaScript weekday numbering and week 0 as “every week,” these mean Sundays plus the second Saturday, Sundays plus second/fourth Saturdays, or Sundays only. That interpretation is inferred and must be confirmed in the old rule evaluator, especially how it determines the nth weekday.

Two policies have no company ID. The exports cannot establish whether they are global defaults, legacy records, or incomplete assignments. Only two of the eleven punch companies have directly scoped week-off policies in this export. Missing direct scope does not prove employees lack a policy; assignments or inheritance may exist elsewhere.

## Holiday policies

All three policies are active for 2026, apply to all teams, and label all holidays `national` and non-optional.

| Policy | Company | Entries |
|---|---|---:|
| HO Holiday | `69cd1e3b50e6c73acc73a918` | 10 |
| Operations Holiday | `69cd1e3b50e6c73acc73a918` | 19 |
| Holiday | `69cd1e3b50e6c73acc73a926` | 10 |

**Confirmed date defect:** Operations Holiday stores “Mahatma Gandhi's Birthday” as `0206-10-02`, despite policy year 2026. Its Extended JSON representation is `{"$date":{"$numberLong":"-55642809600000"}}`. A parser expecting only ISO string dates will also fail on this entry. The likely intended date is `2026-10-02`, but retain the original value and record any correction explicitly.

**Overlapping applicability:** HO Holiday and Operations Holiday have the same company, year, active status, and all-teams scope, but different calendars. No selection or precedence field resolves the overlap here. Do not automatically union the calendars or pick one by name without recovering policy assignments.

“New Year” appears on November 10 in all three calendars, and the third calendar also has “NEW YEAR” on January 1. This may be a regional new year rather than a mistake. Preserve the configured dates and clarify naming with the policy owner. This audit checks internal consistency; it does not verify holiday dates against public calendars.

Only two of the eleven punch companies have directly scoped holiday calendars in this export. Company, team, employee assignment, and inheritance collections are needed to assess actual coverage.

## Migration implications and missing evidence

1. Parse Extended JSON correctly and preserve source IDs with source collection/database identifiers for traceability.
2. Keep raw punches, then derive a reviewed, deduplicated event stream using company + employee + timestamp + type as a candidate duplicate key. Do not delete raw duplicates automatically; equal timestamps are not sufficient evidence in every source system.
3. Prevent auto-checkout retries from inserting the same source event repeatedly through a source event/idempotency key.
4. Normalize business dates while keeping UTC instants; explicitly define the timezone and overnight-shift work-date behavior.
5. Resolve missing company scope and overlapping holiday assignments before calculating attendance outcomes.
6. Correct the year-206 holiday through a documented data correction and validate holiday year against policy year.
7. Recover employee/company/team masters, policy assignments, shifts, leave, regularization records, policy history, and the old attendance evaluator before claiming parity for hours, absence, overtime, or payroll.
8. Inspect live MongoDB indexes and validators separately. Exports contain neither index definitions nor collection validation rules, so existing constraints cannot be established from these files.

Useful target relationships are company -> employees/policy assignments, employee -> raw punches, week-off policy -> day rules, and holiday policy -> holiday entries. Effective-dated assignments and preserved policy history are needed for historical recalculation; current policy documents alone cannot prove which rules applied on earlier dates.

## Reproduce

Run `python3 docs/legacy-mongo-analysis/analyze.py` from the repository. It reads only the three named exports and writes `summary.json` alongside this report. The summary includes exact counts, policy contents, and the largest anomalous day groups using source IDs; it contains no resolved employee names.

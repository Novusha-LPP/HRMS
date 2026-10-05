# Attendance policy behavior and accuracy report

**Test date:** 3 October 2026  
**Requested policy:** 09:30–18:30, 8 standard hours, 60-minute break, 15-minute late/early grace, overtime qualifying at 40 extra minutes, rate 1.5×, one correction approval.  
**Timezone used:** Asia/Kolkata.  
**Conclusion:** The tested attendance calculations and report fields agree with the independent expected values after the zero-duration fix. This is a pass for the finite test matrix, not certification of every possible event stream or production record.

## Test method and coverage

All data was fake and isolated in a disposable PostgreSQL database migrated through the application's current schema. Punches were submitted through the real `/v1/time/punches` endpoint with normal employee authentication. Only the server clock was controlled to exercise reproducible historical times; this does not mean production clients can submit historical timestamps. Policy resolution, event persistence, tenant row-level security, correction approvals, attendance recomputation and report SQL executed normally.

| Test layer | Coverage | Result |
|---|---|---|
| Independent arithmetic matrix | 2,592 cases: 6 hour lengths × 6 break modes × 2 grace settings × 2 overtime settings × 18 punch scenarios | Passed after fix |
| Full API policy combinations | 192 combinations: 6 hour lengths × 4 break modes × 2 grace settings × 2 overtime settings × 2 approval settings | Passed |
| Report snapshots in combination matrix | 192 before correction + 96 while approval pending + 192 after correction = 480 snapshots | Matched stored attendance |
| Eight-hour API boundary checks | 72 cases: 4 break modes × all 18 punch scenarios | Passed |
| Additional multi-visit calculations | 4 cases: automatic deduction, no deduction, explicit break and unfinished second visit | Passed |
| Edge workflows and related regression tests | 57 pytest tests, including existing attendance/report/correction/overtime tests | Passed |

Hour lengths: **4, 6, 8, 9, 10, 12**. Grace: **0 or 15 minutes** for both arrival and departure. Overtime: **disabled or enabled**, threshold **40 minutes**, configured rate **1.5×**. Correction approval: **disabled (immediate application) or one level**.

Calculation break modes: no configured break; configured 60-minute break without auto-deduction; auto-deduct 60 minutes; explicit 30-, 60-, and 90-minute breaks. The full API combination matrix uses the first three plus explicit 60-minute breaks; the separate eight-hour boundary run exercises explicit 30- and 90-minute breaks too.

The 18 calculation scenarios cover zero and one-minute sessions; below/at half-day threshold; below/at standard hours; overtime threshold minus one, exact and plus one minute; 14-, 15-, 15m59s- and 16-minute arrival delays; 14-, 15- and 16-minute early departures; early arrival; and missing OUT.

## How worked time is calculated (rule since 2026-10-05)

**Total** runs from the first check-in to the last check-out. **Deducted** is only the time actually
spent away — checked out between sessions, or on a recorded break (BREAK_START/BREAK_END).
**Worked = total − deducted.** A day without a check-out in between counts in full; the policy's break
is **never deducted automatically** (the old "auto-deduct break" switch has no effect and is no longer
shown). The configured break still defines the scheduled shift, so a 09:30–18:30 shift with a
60-minute break is an 8-hour standard day for half-day and overtime.

For a 09:30–18:30 shift with a 60-minute break and overtime from 40 extra minutes:

| Punches | Total | Deducted | Worked | Overtime |
|---|---:|---:|---:|---:|
| IN 09:30, OUT 18:30 | 540 min | 0 | 540 min | 60 min, PENDING |
| IN 09:30, OUT 13:30, IN 14:30, OUT 18:30 | 540 min | 60 min | 480 min | 0 |
| IN 09:30, BREAK 13:00–13:30, OUT 18:30 | 540 min | 30 min | 510 min | 0: excess 30 is below threshold 40 |
| IN 09:30, OUT 12:00, IN 12:30, OUT 14:00 | 270 min | 30 min | 240 min | 0 (early departure) |

Present / late / half day / early departure and overtime are derived from worked time, lateness from
the first check-in and early departure from the last check-out.

**Checking out after midnight / missed punches.** A check-out up to 24 hours after the check-in
closes that day even when it falls on the next calendar date (the clock keeps showing "Check out"
after midnight), and corrections accept the same window. After 24 hours the check-out is refused
with a "Missed punch" message and the day becomes **MISSED_PUNCH** for HR to correct — flagged by the
employee's next check-in or by the daily `missed-punches` job.

**Removing the configured break while keeping 8h/day changes the derived end to 17:30.** Keeping the end at 18:30 and setting break to zero produces a 9-hour standard day. In the matrix, end time was derived consistently as start + working hours + configured break.

## Requested policy: representative behavior

This table assumes **60-minute auto-deduction**, **15-minute grace**, **8 standard hours**, **overtime enabled at 40 extra minutes**, no rounding, and the default **50% half-day threshold**. Values are whole minutes.

| IN → OUT | Worked | Late | Early | Overtime | Status |
|---|---:|---:|---:|---:|---|
| 09:30 → 18:30 | 480 | 0 | 0 | 0 | PRESENT |
| 09:44 → 18:30 | 466 | 0 | 0 | 0 | PRESENT |
| 09:45 → 18:30 | 465 | 0 | 0 | 0 | PRESENT |
| 09:45:59 → 18:30 | 464 | 0 | 0 | 0 | PRESENT |
| 09:46 → 18:30 | 464 | 1 | 0 | 0 | LATE |
| 09:30 → 18:15 | 465 | 0 | 0 | 0 | PRESENT |
| 09:30 → 18:14 | 464 | 0 | 1 | 0 | EARLY_DEPARTURE |
| 09:30 → 18:29 | 479 | 0 | 0 | 0 | PRESENT |
| 09:30 → 19:09 | 519 | 0 | 0 | 0 | PRESENT |
| 09:30 → 19:10 | 520 | 0 | 0 | 40, PENDING | PRESENT |
| 09:30 → 19:11 | 521 | 0 | 0 | 41, PENDING | PRESENT |
| 09:30 → 14:29 | 239 | 0 | 226 | 0 | HALF_DAY |
| 09:30 → 14:30 | 240 | 0 | 225 | 0 | EARLY_DEPARTURE |
| 09:30 → 09:30 | 0 | 0 | 525 | 0 | ABSENT, after fix |
| 09:30 → missing OUT | 0 completed minutes | 0 | 0 | 0 | PRESENT, still open |

PRESENT is an attendance classification, not proof that all eight hours were worked. Grace permits PRESENT with fewer standard minutes. Status precedence is: zero worked → ABSENT; below half-day threshold → HALF_DAY; then LATE; then EARLY_DEPARTURE; otherwise PRESENT. An employee who is both late and early receives LATE, while both minute fields remain available.

Late minutes and early minutes are **beyond grace**, not the full deviation. For example, 16 minutes late with 15 minutes grace records 1 late minute. Whole-minute truncation also applies: 15m59s late records no lateness beyond the 15-minute grace.

Overtime threshold is a qualification gate: at exactly 40 excess minutes, **all 40 count**. It is not a deduction of the first 40 minutes. Turning overtime off retains actual worked minutes but records zero overtime.

## Corrections and approval

| Workflow | Attendance/report behavior |
|---|---|
| Approval required; correction submitted | PENDING_L1; original attendance and report unchanged |
| One authorized approval | APPROVED; endpoint replacements applied and attendance/report recomputed |
| Approval disabled | APPROVED and applied immediately upon submission |
| Correction rejected | Original attendance/report unchanged |
| Correction cancelled | Original attendance/report unchanged |
| Employee attempts self-approval | Rejected; report unchanged |
| Approve an already approved correction | Rejected |
| Missing OUT corrected | Open record unchanged while pending; after approval, OUT and worked time appear |
| Correction changes previously approved overtime from 40 to 0 minutes | Overtime review is cleared; status becomes NONE |
| Attendance period locked | New punches and correction approval rejected with 409; report unchanged |
| Correction timestamp outside requested business day | Approval rejected with 422; report unchanged |
| Reversed correction IN/OUT | Submission rejected with 422 |

Correction approval and overtime approval are separate workflows. Approving a correction does not automatically approve computed overtime.

## Report accuracy and limits

For each API matrix observation, report `work_date`, `status`, `first_punch_in`, `last_punch_out`, `effective_minutes`, `late_by_minutes`, and `early_departure_minutes` were checked against the actual database row. Arithmetic fields, including gross, break and overtime minutes, were independently checked against an oracle calculated without calling the production calculation helpers.

The attendance report currently **does not offer overtime minutes/status, gross minutes, break minutes, or overtime pay as columns**. Those values were verified in attendance storage/API, not represented as fields that the report currently exposes. The configured **1.5× rate is stored and resolved but no overtime pay is calculated by this report**.

Additional observed limits:

- No attendance row means no report row. A never-punched day is omitted rather than synthesized as ABSENT.
- Missing OUT leaves PRESENT/LATE with zero completed minutes while the session is open; 24 hours after the check-in the day becomes MISSED_PUNCH (see above).
- Superseded 2026-10-05: an OUT after midnight used to be refused and lunch taken as OUT/IN was deducted twice when auto-deduction was on. See "How worked time is calculated".
- Omitted optional policy fields retain defaults; omission is not disabling. Defaults include a 60-minute break allowance, overtime enabled, 50% half-day threshold, UTC timezone, and approval required. The tests set optional rules explicitly.
- Historical rows do not automatically recalculate when a policy is edited or calculation code is fixed. Existing production data was not recomputed.
- Browser timezone controls displayed timestamp formatting; CSV preserves timestamp offsets. The stored business work date is unchanged.
- Report truncation remains possible at the configured row limit, but is explicitly signaled. Use narrower filters for complete exports.

## Defect found and fixed

Identical IN/OUT timestamps previously bypassed final day computation (`last_out > first_in`) and retained PRESENT. The condition now permits equal endpoints, computes zero work and produces ABSENT. The initial arithmetic matrix found 144 failures, all at this zero-duration boundary; after the fix all 2,592 calculation cases passed. The edge API test also verifies the corrected result through actual punch and report endpoints.

## Reproducible evidence

- Test suite: [test_policy_combination_matrix.py](../backend/tests/test_policy_combination_matrix.py).
- 192 observed policy/correction combinations: [attendance-policy-matrix-results.json](attendance-policy-matrix-results.json).
- Eight-hour observed punch boundaries: [attendance-policy-boundary-results.json](attendance-policy-boundary-results.json).

These tests establish the documented behavior for the tested matrix. They do not prove all possible policies, DST zones, rounding intervals, overtime caps, arbitrary imported events, simultaneous requests, browser/CSV interactions, holiday/leave precedence, or production-data integrity. No production records were changed. The isolated test run emitted development JWT-key-length warnings; they did not cause test failures.

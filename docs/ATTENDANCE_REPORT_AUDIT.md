# Punch-in / punch-out report audit

Reviewed 3 October 2026. Changes are local workspace changes; no production data was updated.

## Fixed

- Attendance date equality and inclusive between filters now execute instead of being ignored.
- Department, location and employee filters now execute with bound parameters.
- Invalid dates, reversed/contradictory ranges, unsupported filters and invalid statuses return 422 rather than silently expanding the report.
- Historical department/location uses the assignment effective on the attendance work date. A deterministic lateral join prevents assignment overlaps from multiplying attendance rows.
- Status options include weekend, early departure and pending.
- Worked duration is labelled as minutes, matching its stored unit.
- Run limits are validated (1–10,000). Results signal truncation using an extra-row probe and the UI warns that CSV is partial.
- Runtime filter overrides preserve repeated constraints.
- Builder filter field changes select an operator supported by the new field; between has two date inputs. Running is disabled while metadata is unavailable.
- Saved reports allow run-specific filters, including dates for the monthly summary.
- Breaks in incomplete visits no longer deduct minutes from completed visits. Paired elapsed durations use UTC for daylight-saving folds.

## Verification

`backend/tests/test_attendance_reports.py` covers date operators, native date bindings, invalid inputs, all advertised attendance filters, bounded limits, overnight timestamps, missing punch-outs, historical transfers, tenant/access restrictions, open-session breaks, daylight-saving elapsed time, real punch creation, duplicate-punch rejection, report output following approved corrections, and truncation.

The report tests plus existing workflow, overtime-review and regression tests passed: 39 tests, against a disposable migrated PostgreSQL database. The frontend production build and six existing frontend tests passed; lint reported warnings but no errors. Frontend checks validate compilation and existing utilities; they are not a browser interaction test of the new filter controls.

## Accuracy boundaries

This is a report of stored `attendance_days`, not a reconstruction of every raw punch or every expected work date. Missing attendance rows are omitted; they are not synthesized as absent. First IN and last OUT are daily endpoints; effective minutes come from paired visits, so subtracting those endpoints does not necessarily equal worked time.

Previously stored summaries affected by calculation bugs remain unchanged until explicitly recomputed. No historical production recomputation was performed.

Punch timestamps retain their offsets in CSV. The table renders them in the viewer's browser timezone, which can differ from the attendance policy timezone; the work date remains the stored business date.

Blank filters mean unrestricted history, including in the built-in monthly report. Select the date range before running. Truncated exports require narrower filters for complete output; pagination is not implemented.

The test suite is strong regression evidence, not proof of correctness for every policy, imported event stream, race, timezone transition, or live dataset. Browser interaction testing and production-data reconciliation were not performed.

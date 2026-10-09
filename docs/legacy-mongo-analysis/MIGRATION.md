# October attendance and full policy/calendar migration

Applied on October 6, 2026 to the configured HRMS database (`localhost:5432/hrms`), tenant **Suraj Group** (`suraj-group`). The source MongoDB exports were not changed. RABS employee attendance and assignments were deferred as requested.

| Item | Imported |
|---|---:|
| October 2026 punches | 653 |
| Employees with imported punches | 103 |
| Employee-days calculated or held for correction | 388 |
| Source week-off definitions | 4 |
| Additional Sunday-only legacy fallback | 1 |
| Week-off assignments | 125 |
| Full 2026 holiday calendars | 3 |
| Holiday entries, all months | 39 |
| Employee holiday-calendar assignments | 122 |

The 784 October source punches reconcile to 653 imported Suraj punches plus 131 deferred RABS punches. October coverage ends on October 6 at 11:35 India time in this export; later events are not present in the supplied data. No April–September source punches were imported. All 12 existing native HRMS punches were preserved.

## Rules and assignments

- Operation Weekoff and HO Weekoff: Sundays and the second Saturday off.
- NOVUSHA WEEKOFF POLICY: Sundays and the second/fourth Saturdays off.
- General Week Off: Sundays off.
- Three October employees without an explicit or company-level source week-off policy receive a separate Sunday-only fallback, matching the old evaluator.
- Explicit holiday-calendar assignments take precedence over calendar company metadata. HO and Operations calendars remain separate; their holidays are not combined for every employee in a company.
- All source definitions are retained in the Suraj policy/calendar library. The RABS-specific General Week Off and Holiday definitions remain unassigned there. The RABS tenant was not populated by this run.
- Employee assignments start October 1, 2026. Holiday assignments end December 31, 2026. Earlier assignment history is not reconstructed from a current user snapshot.
- The approved Gandhi Jayanti correction changes October 2, year 206 to **October 2, 2026**. The original source record and correction are retained in the database import audit.

The supplied files do not contain shift definitions. Imported week-off templates inherit the existing HRMS tenant default shift, break, grace, overtime and approval settings. This is a migration of raw attendance events and available calendar rules; it does not establish parity with the old system's missing shift/payroll configuration.

## Attendance requiring attention

Existing native punches overlap legacy punches on **October 3 and October 5** for one employee. Both raw histories were kept. The two derived days are marked `MISSED_PUNCH` with `LEGACY_CONFLICT`, shown as “Imported punches need correction” in the attendance register. Their hours and overtime are zero pending correction; no payable result was inferred from the conflicting sequence. The prior attendance summaries are preserved in the import audit.

Other single-punch and incomplete source sessions retain the current HRMS engine's normal pending/missed-punch behavior. There were 42 computed `MISSED_PUNCH` days in total, including these two conflicts. Attendance should be reviewed before payroll use.

## Verification and recovery

- Each of the 653 stored source punches was compared against its original employee link, timestamp, business date, type, method and creation timestamp.
- All 39 imported holidays are in policy year 2026.
- A post-import dry run created **zero new records**.
- The database schema matches Alembic metadata.
- Synthetic tests cover transaction rollback, repeat imports, source drift, locked periods, native/source conflicts, calendar selection in daily analysis/register/leave counting, and tenant isolation. Attendance policy and register regression checks passed; backend type checking and frontend build passed.

Aggregate verification: [migration-verification.json](migration-verification.json).

Private files (ignored by Git):

- Backup: `/home/aiserver/HRMS/backend/storage/migration-backups/before-exim-attendance-20261006-122036.dump`
- Applied audit: `/home/aiserver/HRMS/backend/storage/migration-backups/exim-october-applied.json`
- Rerun check: `/home/aiserver/HRMS/backend/storage/migration-backups/exim-october-rerun-check.json`
- RABS deferred report: `/home/aiserver/HRMS/backend/storage/migration-backups/rabs-october-deferred.json` — 131 punches across 25 employee IDs needing confirmed mappings. Another 17 RABS users' explicit calendar/week-off assignments were deferred.

The database also contains one `EXIM_ATTENDANCE` import batch with the source file fingerprints, original policy documents, correction and deferred/conflict details. The backup predates the schema and data import; restore it only into a separate database for inspection or a deliberately coordinated recovery, as restoring over HRMS would also replace unrelated records.

## Repeat the import

For the subsequent Suraj policy corrections, names and complete employee week-off coverage, see [policy accuracy reconciliation](SURAJ_POLICY_ACCURACY.md). Coverage is now 189 linked employees after adding 64 missing company/fallback assignments. The counts above describe the original attendance import checkpoint. After holiday-library consolidation, use the policy-only reconciliation script; the full importer preserves its strict changed-record checks.

From `backend`, dry-run (rolls back):

```bash
.venv/bin/python scripts/migrate_legacy_attendance.py \
  --tenant suraj-group --correct-gandhi-date \
  --report storage/migration-backups/exim-october-dry-run.json
```

`--apply` commits. IDs are derived deterministically from tenant, source collection and MongoDB ID. Existing imported rows that differ from the source cause a failure rather than being overwritten. Locked periods and reviewed/rewarded conflicting days are protected. Any unresolved non-RABS identity/company link rolls back the entire import.

# RABS October attendance

Imported **five October 2026 punches for AFZAL GHANCHI**, using the user-confirmed link to HRMS employee **RI_039 (Afzal Ghanchi)**. They cover October 1, 5 and 6. The current RABS attendance engine derived two Present days and one Early Departure day, using existing HRMS policies.

The export contains **131 RABS punches across 25 employees and 89 employee-days**, dated October 1–6, 2026. No later October dates occur in this export. There are no duplicate source events, and all source punches are valid, non-regularized mobile events.

**126 punches for 24 employees remain deferred** because their HRMS employment links are unconfirmed. Name/contact candidates were not automatically turned into links. The import follows the earlier instruction to wait for confirmed identities and does not create new employee records.

## Confirm remaining links

[Employee mapping sheet](/home/aiserver/HRMS/backend/storage/migration-backups/rabs-october-employee-mapping.csv)

[Current RABS employee roster](/home/aiserver/HRMS/backend/storage/migration-backups/rabs-hrms-employee-roster.csv)

Fill `confirmed_hrms_employment_id` with the corresponding `employment_id` from the roster. Afzal's confirmed row is already filled; the other 24 rows are blank. Candidate columns are suggestions, and the importer reads only the confirmation column. Leave an unresolved row blank. The CSVs contain employee identifiers and are stored privately with owner-only permissions.

## Verification and preservation

- Verified all five source timestamps, types, business dates, creation timestamps and mobile sources exactly against the stored punches.
- Added five punch rows and three derived attendance days. All **665 previous punches and 391 previous attendance days** were unchanged, including Suraj records.
- Existing attendance, holiday and leave policy assignments, 194 leave ledger rows and 195 journal transactions were unchanged. RABS leave policies remain unassigned.
- Rerun created **zero punches** and recomputed **zero attendance days**.
- Two synthetic tests passed for explicit mapping, ignoring unconfirmed candidates, atomic rollback, partial reporting, tenant/entity checks, source drift and duplicate-free reruns. Ruff passed for the added scripts/tests.

[Verification counts and attendance dates](rabs-october-attendance-status.json)

Verified backup: `backend/storage/migration-backups/before-rabs-october-20261006-091535.dump`. Before-state, original RABS source punches, dry-run, applied and rerun reports are in the same ignored directory.

## Import remaining confirmed rows

From `backend`, run `.venv/bin/python scripts/import_rabs_october.py --employee-map storage/migration-backups/rabs-october-employee-mapping.csv` for a rolled-back dry run. Add `--allow-partial` to import only confirmed owners and report the rest. Add `--apply` to commit. The importer validates RABS entity scope and employment dates, preserves raw punch IDs, guards locked/reviewed attendance and rejects changes to already-imported punches. It does not change source employee accounts or policy assignments.

`.venv/bin/python scripts/verify_rabs_october.py` verifies the stored before-state and confirmed source records. Additional confirmed employee links require an updated report before verification.

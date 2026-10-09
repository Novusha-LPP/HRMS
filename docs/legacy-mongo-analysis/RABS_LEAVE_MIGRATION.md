# RABS leave definitions

Imported into the existing **RABS Industries India Private Limited** tenant on October 6, 2026. The user instructed us to retain RABS's own settings and keep policies unassigned until employee links are confirmed.

## Imported definitions

| Source definition | Status | Annual entitlement | Carry-forward | Salary deduction |
|---|---|---:|---|---|
| Privilege Leave | Active | 25 | Up to 15 days | Disabled |
| Paid Leave | Active | 12 | Disabled | Disabled |
| Unpaid Leave | Active | 12 | Disabled | **Disabled, as exported** |
| Previous Paid Leave | Archived | 12 | Disabled | Disabled |
| Previous Leave Without Pay | Archived | 999 | Disabled | Enabled |

All five original policy documents are preserved exactly on their bucket policies and in the `EXIM_RABS_LEAVE` import batch. This includes eligibility, service requirements, probation rules, sandwich flags, half-day/backdate restrictions, approval levels and the separate attendance/absence flags.

Each definition has its own type, bucket, mapping and policy set. The two active source `PL` definitions are separate **25-day Privilege Leave** and **12-day Paid Leave** entitlements. Generated target codes distinguish source definitions; their original codes remain in the source documents. Inactive definitions remain archived and cannot be selected as active policies.

Per the subsequent naming request, active names are now **Privilege Leave**, **Paid Leave** and **Unpaid Leave**. Archived names are **Paid Leave (Inactive)** and **Leave Without Pay (Inactive)**. Quotas remain in their entitlement fields. The correction changed only display names and preserved all other fields, including the unassigned status. [Name correction verification](leave-name-verification.json) records the final comparison against the pre-correction backup; earlier migration verification reports describe their original import checkpoints.

The “Unpaid Leave” name conflicts with its disabled salary-deduction flag. Per the user's instruction, that flag was retained and its target `is_paid` is true. Its source `lwp` kind uses an unlimited bucket, consistent with the old controller's balance-check bypass; the 12-day quota remains preserved without an artificial opening credit. No automatic monthly accrual was enabled.

## Assignments and activation

**Zero employee assignments were created**, and none of these sets is a tenant default. Unassigned applications are rejected by the existing imported-policy applicability guard.

RABS's existing HRMS accounts came from Sharanga and have no EXIM employee links. Contact comparison of the 64 source-company EXIM users found 12 candidates, but only two also matched full names. Contact overlap alone is insufficient to establish identity. No account links or employee records were changed. The user chose to leave policies unassigned pending confirmed links.

Before assigning these definitions, validate RABS eligibility and service/probation rules, sandwich counting and the actual HOD/administrator approval route against confirmed employee data. Complete source definitions are retained; this import does not add runtime support for every RABS-specific rule. Staff opening balances require `exim.leavebalances.json` and reconciliation with leave applications. The unrelated driver quota snapshot supplies no staff balances.

The earlier RABS October attendance remains deferred pending employee links.

## Verification

- All five complete source definitions matched exactly; three remain active and two are archived.
- The active PL policies use distinct types and buckets, with entitlements 12 and 25.
- All existing audited leave rows across tenants were unchanged, including Suraj's 189 imported assignments and its native configuration.
- Existing **194 ledger rows, 195 journal transactions and five applications** were unchanged; no new balance, journal, application or assignment rows were created.
- A rolled-back rerun created **zero records**.
- Synthetic RABS and Suraj import tests passed: **3 tests**. Ruff passed for the added scripts/tests. The repository-wide mypy check found four existing errors in `time/holiday_calendars.py`; this turn changed no runtime models or application routes.

[Independent verification](rabs-leave-verification.json)

## Recovery and reproduction

Verified backup: `backend/storage/migration-backups/before-rabs-leave-20261006-090050.dump`. Before-state, dry-run, applied and rerun reports are stored in the same ignored directory with owner-only permissions.

From `backend`, run `.venv/bin/python scripts/migrate_rabs_leave.py` for a rolled-back dry run; `--apply` commits. A changed source export or imported row fails instead of overwriting data. `.venv/bin/python scripts/verify_rabs_leave.py` independently verifies the applied definitions and before-state.

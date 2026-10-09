# Suraj attendance and leave policy reconciliation

Applied on October 6, 2026. The original MongoDB exports remain unchanged. Verification covers the available policy documents and linked employees; it does not establish complete historical attendance/payroll parity.

## Attendance

The attendance-policy library now uses readable names: **Operations Week Off**, **Head Office Week Off**, **Novusha Week Off**, and **Sunday Week Off (Fallback)**. The retained, unassigned source RABS definition is clearly labelled **General Week Off (RABS)**. The existing **Standard General Shift** remains unchanged.

The original import assigned explicit week-off policies and a Sunday fallback only for three October punch owners. Reconciliation found **64 additional linked employees** without their old effective rule: seven needed the company-level Head Office policy, and 57 needed the old Sunday-only fallback. These assignments now start on October 1, 2026, consistently with the original migration.

| Effective rule | Linked employees | Days off |
|---|---:|---|
| Head Office Week Off | 93 | Every Sunday and the second Saturday |
| Operations Week Off | 19 | Every Sunday and the second Saturday |
| Novusha Week Off | 17 | Every Sunday and the second/fourth Saturdays |
| Sunday Week Off (Fallback) | 60 | Every Sunday |
| Total | 189 | |

Resolution follows the old `PolicyResolver.js`: active explicit employee policy, then an active policy for the source company, then Sundays only. Missing company information, ambiguous company defaults and unsupported team scopes cause the correction to fail instead of guessing.

All 365 dates in 2026 were independently compared for each of the four retained source definitions and the fallback: **1,825 rule comparisons**. Employee policy resolution was checked at both ends of October. None of the newly assigned employees had a saved October-or-later attendance result, so no historical results were recalculated.

## Leave

All **18 complete Suraj source definitions** and effective leave policies for **189 linked employees** were compared with the exports. **107 employees** have Privilege Leave, and all 189 have Leave Without Pay. Source-company filtering, explicit PL eligibility, automatic company LWP access and the preserved native entitlements remain intact.

- Privilege Leave: 25 annual days, maximum 15 per application, seven days' notice and carry-forward capped at 15 days.
- Leave Without Pay: source 0/999 quotas retained; an unlimited unpaid bucket follows the old controller's balance-check bypass. Maximum 30 days per application, one day's notice, and the source-specific 10-day consecutive limit where present.
- Both imported type displays now show the exported **one-day minimum**. Allowed half-day applications still use the separate half-day exception.
- Readable company/leave names are retained. One duplicate Novusha set name now includes **Alluvium Employees**, because those linked employees belong to Alluvium in HRMS while their source company ID selects the Novusha policy. Their confirmed links and source policy selections were preserved; the naming correction does not infer a transfer or change identity.

## Verification and recovery

Six isolated migration tests passed, including a regression for company-default and Sunday-only policies on employees with no October punches, working-day leave allocation, rollback, repeat imports, native data preservation and source drift protection. Ruff passed for the changed scripts/tests. A policy-correction rerun made zero changes, and the Suraj leave importer created zero rows on its rolled-back rerun.

The correction saved a private before-state under `backend/storage/migration-backups/before-suraj-policy-correction-*.json` and an `EXIM_SURAJ_POLICY_CORRECTION` import audit. Comparison across policy, leave, attendance, punch and holiday tables allowed only the five planned attendance names, two leave minimum fields and 64 new assignments. All existing attendance results, balances, transactions, leave applications, other assignments and other tenants were unchanged. The subsequent single leave-name correction has its own private before-state and report.

[Applied verification](suraj-policy-verification.json), [rerun verification](suraj-policy-dry-run.json), and [independent preservation check](suraj-policy-preservation-verification.json). The final check compared 2,172 pre-existing rows and confirmed exactly the five attendance names, two minimum fields, one disambiguated leave name and 64 new assignments described above.

From `backend`, run `.venv/bin/python scripts/reconcile_suraj_policies.py` to audit in a rolled-back transaction. `--apply` saves a before-state and commits supported corrections. Use this policy-only verifier after holiday-library edits: the original full attendance importer intentionally rejects archived or otherwise changed imported calendar records instead of restoring them or creating duplicate holidays.

## Limits of old-data accuracy

Legacy shift definitions, grace/overtime configuration and staff leave balances were not exported. HRMS therefore retains the existing shift settings and balances rather than inventing values. Legacy named approver routes have not been reconstructed. The old leave calculation code also applies sandwich counting even when the exported policy flag is false; HRMS follows the exported false flag. Complete source policy documents remain preserved for further reconciliation.

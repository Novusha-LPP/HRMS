# Suraj leave migration

Applied to the existing `suraj-group` database on October 6, 2026. Assignments take effect on **October 1, 2026**. RABS remains deferred.

## Imported

- **18 active definitions**: nine Privilege Leave and nine Leave Without Pay policies across nine legacy company IDs.
- Two identifiable HRMS types: **Privilege Leave (Suraj Group)** (`EXIMPL`) and **Leave Without Pay (Suraj Group)** (`EXIMLWP`). Original source names/codes are preserved in the source documents. Existing HRMS types and balances were retained.
- **189 employee assignments**: all 189 have LWP access; **107 have explicitly assigned Privilege Leave**.
- **37 policy sets**: 18 separately retained source definitions plus 19 employee combinations. Combinations include native bucket rules where a native policy already applied. No tenant default or company assignment was replaced.
- Complete original policy documents are stored on the imported bucket policies and in the `EXIM_LEAVE` batch, with source fingerprints and employee/source mappings.

PL retains its **25-day annual entitlement and 15-day carry-forward cap**. An annual entitlement is a rule, not an imported available balance. No monthly accrual credits, lapse schedule or first-year proration were invented.

LWP uses an unlimited unpaid bucket. The old controller explicitly bypasses its balance check for `lwp`; its default 2,000-day balance is a placeholder. Original 0/999 quotas remain in the policy documents without creating artificial credits.

The old Suraj controller filters employee references by source company and supplies the company's active LWP policy. The import follows that behavior. **Four foreign-company references on two users** were retained for review and excluded from applicability. PL access recoverable solely from a missing legacy balance export remains pending.

## Behavior and limits

Imported applications require an assigned bucket policy. Validation applies source duration limits, advance notice, backdate prohibition and the explicit **10-calendar-day consecutive limit** on the two LWP definitions with that restriction. Permitted half days can pass the one-day minimum, matching the old calculator's special case. Native type validation is unchanged.

The old controller supplies three approval stages despite empty policy level arrays. Imported types require three HRMS approval levels; existing configured HRMS flows take precedence. **Old named approver groups and requester-specific bypasses were not migrated**; their definitions/team exports were not supplied. No auto-approval was enabled.

Salary, absence and attendance-percentage flags are retained in source documents. HRMS represents LWP as unpaid and PL as paid; independently configurable processing of all three flags is not added by this import.

## Deferred

- Five RABS policies and two inactive initial-company policies.
- All **100 driver quotas**, which lack company/policy links and are not staff balances.
- Opening balances, usage/history and pending leave. These require **`exim.leavebalances.json`**, ideally reconciled with leave applications. Existing HRMS balances remain available for their original types. **New EXIM PL balances have not been funded**, so paid submission still requires actual ledger balance.

## Verification

An independent read-only verifier confirmed all 18 original definitions exactly and all 189 effective assignments. All audited existing leave rows were unchanged, including **194 monthly ledger rows, 195 journal transactions and five applications**. RABS leave data was unchanged. A rerun created **zero records**.

Synthetic tests passed for rollback, reruns, changed-source rejection, applicability, native entitlements, application limits and actual unpaid HTTP submission without a balance. Existing leave lifecycle and resolver tests passed. Ruff, mypy and Alembic schema checks passed.

[Verification counts](leave-migration-verification.json)

On October 6, the user requested proper leave names. Imported labels now use full leave names and readable company names, without migration prefixes or ID fragments. Sets that also preserve native entitlements are marked “Additional Leave.” Only name fields were corrected; original codes, IDs, rules, assignments and balances remain unchanged. Both migration scripts were rerun in rollback mode and created zero records. [Name correction verification](leave-name-verification.json) compares the complete leave data with the backup saved immediately before renaming. Earlier migration verification reports describe their original import checkpoints.

## Recovery and reproduction

The later [Suraj policy accuracy reconciliation](SURAJ_POLICY_ACCURACY.md) verified all 18 source definitions and 189 employee policies again, aligned the displayed minimum with the exported one-day rule while retaining half-day handling, and completed the attendance week-off coverage used by leave-day counting.

Verified PostgreSQL backup: `backend/storage/migration-backups/before-exim-leave-20261006-073732.dump`. Private before-state, dry-run, applied and rerun reports are in that ignored directory with owner-only permissions.

From `backend`, run `.venv/bin/python scripts/migrate_legacy_leave.py` for a rolled-back dry run. `--apply` commits. Changed sources or imported rows fail rather than overwrite data. `scripts/verify_legacy_leave.py` independently compares the before-state and applied import.

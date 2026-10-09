# Legacy leave export assessment

Checked `exim.leavequotas.json` and `exim.leavepolicies.json`, with references resolved against `exim.users.json`. These are read-only checks of local exports. No leave data was imported into HRMS and no source files were changed.

## Two separate data stores

**Leave quotas: 100 records for 25 drivers**, all for 2026. Every driver has the same four allocation categories. All 25 `driver_id` values match source users whose role is `driver`; none of those users has a company/company ID in the user export. The quota records have no company ID or leave-policy ID.

| Quota category | Days per driver | Total allocated | Total used | Remaining |
|---|---:|---:|---:|---:|
| Sick | 5 | 125 | 0 | 125 |
| Casual | 10 | 250 | 2 | 248 |
| Emergency | 3 | 75 | 0 | 75 |
| Paid | 12 | 300 | 0 | 300 |
| **Total** | **30** | **750** | **2** | **748** |

Two drivers each used one Casual day; 98 quota records have zero usage. IDs and `(driver_id, leave_type, year)` keys are unique. There are no negative allocations/usages or usages exceeding allocation. Update timestamps range from May 1 to September 10, 2026; this is a quota snapshot with no leave application dates, pending requests or usage transaction history.

These quotas should not be used as staff leave balances. They belong to the driver leave system, and their `Sick/Casual/Emergency/Paid` categories do not directly identify the company `PL/LWP` policies. Driver company/employment links and explicit type mapping would be needed to import them into HRMS.

**Leave policies: 25 definitions across 11 source company IDs**, with 21 active and four inactive. Source company IDs do not necessarily map one-to-one to current HRMS legal entities: the earlier employee migration merged the legacy “Suraj Forwarders” entity into Suraj Forwarders Private Limited, and the initial company ID also appears in inactive legacy policies.

| Active policy code | Annual quotas | Definition counts |
|---|---|---|
| PL | 25 days | 10 |
| PL | 12 days | 1 |
| LWP | 999 days | 7 |
| LWP | 0 days | 2 |
| LWP | 12 days | 1 |

Policy definitions contain eligibility, carry-forward, application restrictions, approval levels, payroll/attendance deduction flags and, in five documents, explicit accrual settings. They are rules, not employee balances. Policy ObjectIds are unique, and no policy has a minimum application duration greater than its maximum.

## Issues to resolve before migration

1. **An active PL code collision in RABS.** Privilege Leave (25 days, carry-forward capped at 15) and Paid Leave (12 days, no carry-forward) both use `PL` for the same company. Privilege Leave has no explicit source-user references; Paid Leave has 45. They are distinct definitions, so matching by company + code alone would merge different entitlements. Retain source policy IDs and distinguish the target types/buckets or archive an obsolete definition only after confirming its status.
2. **Unpaid naming and salary flags disagree.** The active RABS “Unpaid Leave” has type `lwp` and quota 12, but `deduct_from_salary=false`. Its `counted_as_absence` flag is also false, while `affects_attendance_percentage=true`. Preserve these fields for review; do not silently determine payroll behavior from the policy name.
3. **LWP quota semantics differ.** Active policies use 0, 999 or 12 days. Zero and 999 may represent special/unlimited behavior, but the exports alone do not establish that interpretation. HRMS supports an unlimited bucket, so confirm the old evaluator before creating a literal 999-day entitlement or a zero-balance block.
4. **Most policies leave approval levels empty.** Nineteen active policies have empty level arrays while `auto_approve_if_balance=false`. Two active RABS policies explicitly require one HOD approval. Empty arrays do not establish auto-approval; the old application may supply default approvers.
5. **Employee overrides cross source-company boundaries.** There are five policy references whose company differs from the user's company: four references belong to two users assigned other companies' policies, and one belongs to a user without a company. These can be intentional overrides or data issues. Preserve them for review rather than treating every company mismatch as a broken reference.
6. **There is no staff leave-balance snapshot here.** Annual quota cannot establish the available balance after taken/pending leave, carry-forward, encashment and lapse. Importing policies must not automatically grant full annual balances to existing staff.

All 306 explicit policy references across 181 source users resolve to a policy in this export, and none references an inactive policy. This is a useful basis for migration. Users without explicit policy lists may still depend on company defaults; those lists alone are not the complete eligibility model.

## HRMS mapping and behavior gaps

| Source | HRMS representation / consideration |
|---|---|
| Policy name/type/code, status, application limits, notice, document requirement | `LeaveType`; company variants need distinct source mappings |
| Annual quota and accrual | `LeaveBucketPolicy` and `LeavePolicySet`; confirm yearly accrual rate semantics before translating |
| Carry-forward enabled and cap | `LeaveBucketPolicy`; source PL caps are 15 days |
| Minimum service and probation eligibility | `LeaveBucketPolicy`; the active RABS Paid Leave requires six months, permanent employment and disallows probation |
| Company/employee policy applicability | `LeavePolicyAssignment`; retain explicit employee overrides and account for merged company IDs |
| Actual opening/remaining balances | Leave ledger and immutable transaction journal through the accounting engine; require an authoritative balance snapshot |
| Explicit HOD approval | Current configurable approval flows/reporting manager mapping; preserve mandatory approval rather than guessing from empty levels |
| Employment-type whitelist | No direct equivalent field in the current leave models |
| Sandwich counting, per-policy half-day toggle, backdate window, separate consecutive-day/gap limits and conditional document threshold | No direct equivalent fields in the current leave models; application limits and notice only cover part of this behavior |
| Separate salary deduction, attendance-percentage and absence-counting flags | Current `LeaveType.is_paid` cannot represent all three independently |

All policies allow half days but set minimum application days to 1. HRMS currently validates requested working days against that minimum, so a standalone half-day application could be rejected if imported literally. Confirm the intended old-system behavior before choosing a target minimum; a flag permitting half days does not by itself override an application minimum.

The five explicit accrual blocks all say yearly, rate 1, calendar-year start, while annual quotas vary. The relationship between `accrual_rate` and `annual_quota` needs verification in the old leave accrual logic; the export does not explain the rate's unit.

## Data needed for a staff balance migration

The old application has a separate `LeaveBalance` model containing employee ID, company ID, leave-policy ID, year, opening/closing balances, usage, pending approval, carried-forward, encashed and lapsed amounts, plus monthly usage. An export such as **`exim.leavebalances.json`** would supply staff balance evidence that these driver quotas do not provide. Leave application/approval history would additionally support reconciliation of used and pending amounts.

RABS remains deferred under the earlier migration decision. No driver, Suraj or RABS leave balances or policies were imported as part of this analysis.

Reproduce with `python3 docs/legacy-mongo-analysis/analyze-leave.py`. Exact counts, original policy definitions, fingerprints and reference exceptions are in [leave-summary.json](leave-summary.json).

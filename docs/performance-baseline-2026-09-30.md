# Performance baseline and plan — 30 September 2026

Measured with the harness in `backend/perf/` (see its README), against **synthetic data only**,
in a private Postgres 16 cluster. The code is the working tree at `c716f55` plus the uncommitted
leave-engine changes (migration 0022).

## Dataset (`perf-2k`)

2,000 employees across 4 companies and 100 org units, with 3-level reporting lines.
- **Attendance:** 305k attendance days and 611k punches, covering 6 months.
- **Leave:** 2,932 leave applications (1,993 approved by their real line managers), plus 8 monthly accrual runs.
- **Personas:** employee, team lead, department head, HR (whole tenant, 2 companies, 1 department) and tenant admin.

A 200-employee tenant (`perf-200`) was used to confirm how costs scale.

## Load (4 uvicorn workers, working-day mix: punch rush, employee, manager, HR)

| Users | Throughput | p50 | p95 | p99 | Peak active DB connections |
|---|---|---|---|---|---|
| 200 | 103 req/s | 8 ms | 180 ms | 270 ms | — |
| 600 | 299 req/s | 11 ms | 210 ms | 380 ms | 3 (of 49 open) |

At this company size the system is **not throughput-bound**. The host CPU was about 80% idle at
600 users. The p95/p99 tail comes almost entirely from four endpoints (below) plus bcrypt login
(~185 ms by design).

## Per-request fixed cost

Every authenticated request runs these statements before the endpoint's own code, plus BEGIN/COMMIT:

1. `set_config('app.tenant_id')`
2. Tenant status check
3. Account and employment check
4. Due personnel-actions lookup (`apply_due_actions`)
5. Role assignments
6. Direct reports (managers only)
7. Recursive reporting chain (managers only)

So `/v1/auth/me` costs 9–11 statements, of which the endpoint itself needs 4. In the 600-user run,
role resolution alone ran 44,840 times and the account check 37,295 times. Locally a round trip
is ~0.1 ms (unix socket). A managed database across the network is typically 0.3–1 ms, so in
production this overhead is roughly **3–7 ms added to every request**.

The RLS helper `current_tenant_id()` is `SECURITY DEFINER`, so Postgres cannot inline it. Its body
ran **1.15 million times** as a separate nested statement during the 600-user run.

## Endpoints that do not scale (2,000 employees, sequential, in-process)

| Endpoint (persona) | p50 | Statements | Response | At 200 employees | Cause |
|---|---|---|---|---|---|
| `GET /v1/leave/applications` (HR, all) | **830 ms** | **2,938** | 1.9 MB | 86 ms / 296 statements | One `leave_approval_actions` query per application (N+1). No pagination. ~600 ms is Python building 2,932 objects |
| `POST /v1/leave/accrual/run` (one month) | **30.5 s** | tens of thousands | — | 2.8 s | Per employee × per leave type: FY lookup, entitlement resolution, idempotency check, insert — in one request and one transaction |
| `GET /v1/time/daily-analysis` (HR, all) | 131 ms | 227 | **1.07 MB** | 62 ms | Recursive org-ancestry query once per org unit (72); whole-tenant payload for one day; ~2/3 of the time is Python |
| `GET /v1/leave/applications?status=PENDING_L1` (HR) | 153 ms | 642 | 314 KB | 20 ms | Same N+1 |
| `GET /v1/users` (admin) | 23 ms (p95 60) | 6 | **780 KB** | 116 KB | Every account in one unpaginated response |
| `POST /v1/reports/{id}/run` (limit 1000) | 110 ms | 7 | 320 KB | 19 ms | Sequential scan of all 308k attendance rows |
| `GET /v1/time/overtime/pending` (HR) | 23 ms | 6 | 0 KB | 5 ms | Sequential scan of 337k rows to find no pending overtime |
| `GET /v1/dashboard/hr` (HR, all) | 20 ms | 23 | 6 KB | 10 ms | Sequential scan of `attendance_days` for a single date (335,861 rows removed by filter) |

Everything else — self-service, manager dashboards, paginated employee lists and attendance
ranges — costs 1.5–10 ms and 5–12 statements, and stays flat as data grows.

With 0.5 ms of network per round trip, the leave list for HR would take roughly **2.3 s** in production.

## Fixes already verified on the benchmark database

These three changes were applied only to the throwaway database, then all 53 endpoint/persona
rows were re-run:

```sql
CREATE INDEX ix_attendance_tenant_date ON attendance_days (tenant_id, work_date);
CREATE INDEX ix_attendance_ot_pending  ON attendance_days (tenant_id, work_date) WHERE ot_status = 'PENDING';
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE
  AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;  -- no SECURITY DEFINER
```

| | DB time before | after |
|---|---|---|
| `overtime/pending` (HR) | 24.0 ms | **0.5 ms** |
| `report run` | 105.1 ms | **16.7 ms** |
| An attendance range query, in isolation | 2.08 ms | 1.39 ms (RLS function only) |
| Sum across all 53 rows | 762 ms | **581 ms (−24%)** |

## Plan, ordered by measured impact ÷ effort

| # | Change | Evidence | Target | Effort |
|---|---|---|---|---|
| 1 | Migration: the two indexes and the inlinable `current_tenant_id()` above. Create indexes `CONCURRENTLY` in production | Verified: −24% DB time; OT pending 48x, report 6x | Done in one migration | S |
| 2 | Leave applications: keyset pagination (`applied_at, id`, max 100) and history loaded in one `WHERE application_id = ANY(:ids)` query — or history only on the detail endpoint. Frontend pages through it | 2,938 statements / 830 ms, linear in data | ≤ 10 statements, < 50 ms per page, at any size | M |
| 3 | Accrual: one set-based `INSERT … SELECT` per leave type (entitlements resolved once per policy, not per employee), run as a scheduled job — not an HTTP request | 30.5 s at 2,000 employees → ~150 s at 10,000 | < 5 s at 10,000 employees, outside the request path | M |
| 4 | Request pipeline: fold set_config, tenant check and account check into one statement. Move `apply_due_actions` to the daily job (also add `scripts/` to the image). Cache the resolved scope per `(user, token_epoch, tenants.authz_version)`, with triggers bumping the version when roles, assignments, managers or org units change | 7 of 9–11 statements are overhead; the top two DB calls under load | 1–2 overhead statements per request | M |
| 5 | Daily analysis: resolve org ancestry for all units in one recursive query; paginate or filter server-side; slimmer rows | 227 statements, 1 MB for one day, 2/3 Python | < 30 ms, < 100 KB per page | M |
| 6 | Pagination sweep for unbounded lists (`/v1/users` first), using one `Page[T]` shape | 780 KB for 2,000 accounts | Max 200 rows per response | S–M |
| 7 | Query budgets in CI: `assert_max_queries` on the endpoints above, using `core/perf.py`, so N+1s cannot come back | — | Fails the PR on regression | S |
| 8 | gzip/brotli for JSON at the proxy | 1–2 MB JSON bodies | ~10x smaller on the wire | S |

## Results after steps 1 and 2 (same dataset, same harness)

Step 1 is migration `0023_performance_indexes`. Step 2 changed `GET /v1/leave/applications`:
- keyset pagination with `limit` (default 100, max 200) and `after=<last id>`
- history batched into one query
- scope filtered in SQL instead of an `IN` list
- several statuses accepted, comma-separated

It also added `GET /v1/leave/applications/summary`. The inbox, dashboard and Leave page now
each ask for only what they show.

| Endpoint (persona) | p50 before | after | Statements | Response |
|---|---|---|---|---|
| leave applications (HR, all) | 830 ms | **5.1 ms** | 2,938 → 7 | 1.9 MB → 46 KB (page of 100) |
| leave applications pending (HR) | 153 ms | **5.1 ms** | 642 → 7 | 314 → 49 KB |
| leave applications (dept head) | 222 ms | **9.3 ms** | 769 → 9 | |
| dashboard leave card | (whole list, above) | **3.3 ms** via `/summary` | 7 | 0.4 KB |
| app-shell inbox (every HR page load) | (whole list, above) | **4.0 ms** (decision statuses, 50) | 7 | 25 KB |
| overtime pending (HR) | 23.1 ms | **1.8 ms** | 6 | |
| report run (limit 1000) | 110.5 ms | **22.5 ms** | 7 | |
| **Sum over all 53 baseline rows** | **2,204 ms** | **465 ms (−79%)** | DB time 762 → 197 ms | |

A deep page costs the same as the first. Walking all 30 pages of 2,932 applications, every page
took 4–10 ms and 8 statements, and each row came back exactly once. Benchmarks were run with
`HRMS_LOG_LEVEL=WARNING`, because per-request INFO logging (added separately) was not in the baseline.

## Results after step 3 (monthly accrual)

`run_accrual` now resolves everything up front: FY months in one query, policy sets once per
placement (org unit + legal entity) rather than per employee, and existing accruals once per
bucket. It then credits each leave type with `engine.record_accruals`, whose three set-based
statements replace ~8 per employee. Employees with ledger rows after the accrual month (a
back-dated run) still go through `record_transaction`, so the forward cascade has one
implementation.

Measured by seeding a fresh 2,000-employee tenant (`perf-2k-b`): 8 monthly runs of 6,000
credits each. Both tenants ended with exactly 48,000 accrual transactions.

| | Before | After |
|---|---|---|
| 8 monthly runs, total | 217 s | **8.8 s** |
| Slowest run | 30.5 s | **4.05 s** (the first month; 2.3 s the second) |
| Steady-state run | ~27 s | **~0.4 s** |

The first two months are probably slower because of planner statistics on a freshly empty
ledger. Unverified.

Correctness: `tests/test_accrual_bulk.py` builds the same scenario in two tenants. One is
credited by the new code, the other by a copy of the old per-employee loop. Every ledger
row and journal entry is compared exactly, floats included. The scenario covers:
- all four policy tiers, including a nested department and an archived policy set
- the probation and minimum-service gates
- a January financial year
- ledger rows before, at and after the month, including leave on hold
- two leave types sharing a bucket

The test catches each of these deliberately introduced bugs:
- opening a new row at 0
- previous balance ignoring held leave
- skipping the back-dated fallback
- dropping `granted` from the closing formula

It also exposed a pre-existing nondeterminism. The leave-type query had no `ORDER BY`, so
when two types share a bucket, which one the accrual was recorded against depended on
physical row order. Types are now processed oldest first.

## Results after step 4 (per-request overhead)

`get_session` now makes two statements where it used to make five:
1. `set_config`
2. One query returning tenant status, account + employment state, the caller's live role grants,
   and whether any scheduled personnel action is due

`resolve_scope` uses those grants instead of querying again. `apply_due_actions` only runs
when something is due, using the same `date.today()` cut-off as before.

| | Baseline | After step 2 | After step 4 |
|---|---|---|---|
| Statements, simplest authenticated GET (`/v1/leave/types`) | 5 | 5 | **3** |
| Statements, sum over 51 benchmark rows | 6,712 | 795 | **646** |
| p50, sum over 51 rows | 2,204 ms | 465 ms | 475 ms |

Local latency is flat because a unix-socket round trip is ~0.1 ms. The saving shows up against
a networked database (0.3–1 ms per round trip), as roughly 1–3 ms per request and 3 fewer
statements of load on every call.

Deliberately not done, and why:
- **Caching the resolved scope across requests.** Scope depends on the current date
  (assignment and manager effective dates) and on `role_assignments.expires_at`, so it can
  change at midnight with no write. A write-driven version counter would miss that.
- **Moving scheduled actions to a job.** Nothing schedules jobs in deployment yet, so moving
  them out of the request path would stop separations from taking effect. The due check
  is now free instead.

Tests in `tests/test_request_overhead.py` pin the statement count at 3. They also check that
a removed role, a suspended tenant and a disabled account each take effect on the very next
request with the same token.

**Deprioritised by the measurements:**
- Connection pooling (PgBouncer/RDS Proxy) as a throughput fix. At 600 users there were at most
  3 active DB connections. It's still needed later to cap total connections across many
  containers, but not for speed.
- Login tuning. It's ~185 ms of bcrypt by design and held at ~50 logins/s with no degradation.

**Not measured yet:**
- A 10,000-employee tenant: the host was under memory pressure. Linear extrapolation from 200 → 2,000 is used above.
- Network latency to a real managed database.
- Write-heavy month-end flows other than accrual.

Also observed: `GET /v1/leave/ledger` and `/v1/leave/transactions` return 403 when an EMPLOYEE
asks for their own `employment_id`. Check whether that's intended.

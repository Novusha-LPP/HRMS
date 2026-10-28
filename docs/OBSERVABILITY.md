# Observability

How to tell what the HRMS API is doing, and what to do when an alert fires.

| Signal | Where it comes from | Where it goes |
|---|---|---|
| Logs | `hrms/core/logging.py`, `core/middleware.py` | stdout, one JSON object per line → your log collector (e.g. CloudWatch Logs) |
| Errors | `hrms/core/error_tracking.py`, `frontend/src/lib/errorTracking.ts` | Sentry |
| Metrics | `hrms/core/metrics.py` → `GET /metrics` | Prometheus → Grafana (`ops/`) |
| Health | `hrms/core/health.py` | load balancer / orchestrator, blackbox probe |
| Build | `hrms/core/version.py` | `/health`, the `X-App-Version` header, every Sentry event |

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `HRMS_LOG_FORMAT` | `console` (`json` in production) | `json` for collectors, `console` for a terminal |
| `HRMS_LOG_LEVEL` | `INFO` | Every request writes one access line at INFO. 4xx and slow requests log at WARNING, 5xx at ERROR |
| `HRMS_LOG_SLOW_REQUEST_THRESHOLD_MS` | `1000` | Requests slower than this are flagged `slow_request` |
| `HRMS_SENTRY_DSN` | unset (off) | Backend error tracking |
| `HRMS_SENTRY_ENVIRONMENT` | `HRMS_ENVIRONMENT` | e.g. `staging` or `production` |
| `HRMS_SENTRY_TRACES_SAMPLE_RATE` | `0` | Share of requests traced for performance; 0 = errors only |
| `HRMS_METRICS_ENABLED` | `true` | Serve `/metrics` |
| `HRMS_METRICS_TOKEN` | unset | Bearer token the scraper must send. **Required in production** while metrics are on |
| `VITE_SENTRY_DSN` (frontend build) | unset (off) | Web-app error tracking. The SDK isn't even bundled without it |
| `VITE_SENTRY_ENVIRONMENT` (frontend build) | build mode | |

## Logs

Every line is one JSON object with `timestamp`, `level`, `logger` and `message`, plus these
when known: `request_id`, `tenant_id`, `user_id` and `client_ip`. Exceptions carry type,
message and traceback. Uvicorn's own lines use the same format.

- **Request ids.** Every response carries `X-Request-ID`. The web app sends its own
  (`req_` + 32 hex); the API keeps any caller-supplied id of at most 64 characters from
  `[A-Za-z0-9._:-]`, and replaces anything else. Error bodies include it as `request_id`, and
  the web app shows it as "Ref: …". Search your logs for that id to get the whole request.
- **Redaction.** Before a line is written, values under sensitive keys are replaced with
  `***REDACTED***`: passwords, tokens, auth headers, cookies, PAN, Aadhaar, salary, bank
  accounts, OTPs. PAN and Aadhaar numbers inside free text (messages, exception text,
  tracebacks) are masked as `ABCDE****F` / `********0123`. Keys match on whole words, so
  `company_name` is left alone while `pan_number` and `accessToken` are masked.
- **Client IP** is the address uvicorn resolved with `--proxy-headers`, trusting only the
  proxies in `--forwarded-allow-ips`. Configure that for your load balancer, or every request
  will show the proxy's address.

## Error tracking (Sentry)

Set `HRMS_SENTRY_DSN` on the API and build the web app with `VITE_SENTRY_DSN`. Both report
as release `hrms@<version>`, tagged with the commit. Backend events carry `request_id` and
`tenant_id` tags, so an event links to its logs.

What is *not* sent, because this is an HR system:
- request bodies, cookies and stack-frame local variables;
- names or emails: users are identified by account id only;
- sensitive values in headers, query strings, messages, exception text and breadcrumbs,
  which pass through the same redaction as the logs.

`tests/test_error_tracking.py` captures a real event and checks this. The web app reports
crashes and uncaught errors only. It never reports failed API calls: the API reports its
own 5xx errors, and a 4xx is an outcome, not a bug.

## Metrics

`GET /metrics` (Prometheus text format). Metric names and labels are listed at the top of
`hrms/core/metrics.py`. Routes are labelled by template (`/v1/employees/{employment_id}`),
and paths that match no route share the single label `unmatched`.

- **Protect it.** Set `HRMS_METRICS_TOKEN` and give Prometheus the same token
  (`authorization.credentials_file`, see `ops/prometheus/prometheus.yml`). Also block
  `/metrics` at the public proxy.
- **Workers.** Counters are per process. Run one uvicorn worker per container (the Dockerfile
  default) and scrape every container. If you run `--workers N`, set
  `PROMETHEUS_MULTIPROC_DIR` to an empty directory so counters aggregate across workers.

### The monitoring stack (`ops/`)

`ops/docker-compose.monitoring.yml` runs five services on the host network, each bound to
127.0.0.1 only:

| Service | Address | What it does |
|---|---|---|
| Prometheus | `127.0.0.1:9090` | Scrapes `/metrics`, evaluates `ops/prometheus/alerts.yml` |
| Blackbox exporter | `127.0.0.1:9115` | Probes `/health/ready` locally (`hrms-ready`) and both public URLs through Cloudflare (`hrms-public`) |
| Node exporter | `127.0.0.1:9100` | Host memory and disk (`hrms-host`), plus the backup-age metrics written as text files to `HRMS_MONITORING_TEXTFILE_DIR` (default `/srv/hrms-monitoring`) |
| Alertmanager | `127.0.0.1:9093` | Groups alerts and sends them to the receiver in `ops/alertmanager/alertmanager.yml` |
| Grafana | `127.0.0.1:3100` | Five dashboards in *HRMS* and both data sources are provisioned from `ops/grafana/` |

The dashboards link to each other and share the selected time range:

- **HRMS Overview** (`/d/hrms-overview`): API/public availability, response speed, errors,
  CPU, memory, disk, database pool utilization, background-job freshness and active alerts.
  **Active users** counts distinct authenticated users with successful API activity during
  the dashboard's selected time range. `hrms_user_last_activity_timestamp_seconds` uses
  stable HMAC fingerprints instead of account or tenant IDs, allowing Grafana to deduplicate
  users across instances. Logout retains historical activity. Per-process last-seen records
  are kept for up to 30 days; Prometheus retains historical samples according to its TSDB
  retention. History starts when this metric was introduced and is sampled on each scrape.
  Changing the API signing key changes fingerprints, so a range spanning key rotation may
  count the same user twice. All instances must use the same key for deduplication.
- **HRMS API** (`/d/hrms-api`): traffic, latency, errors, slow endpoints and sign-in outcomes.
- **HRMS Database** (`/d/hrms-db`): API connection-pool usage, SQL volume and SQL time by
  endpoint. These are application observations; PostgreSQL locks, replication and internal
  statistics require a separate PostgreSQL exporter, which is not currently configured.
- **HRMS Infrastructure** (`/d/hrms-infra`): host CPU, load per core, memory, disk capacity,
  disk/network throughput, public-site probes and infrastructure alerts.
- **HRMS Employment Lifecycle** (`/d/hrms-lifecycle`): rejoins per day by whether earlier
  service continued or started fresh, unused leave settled for leavers (lapsed, paid out,
  held), held leave closed by the daily `leave-holds` job, company transfers and hires refused
  because the person already had an employment. Metrics: `hrms_rejoins_total{mode}`,
  `hrms_leave_separation_settlements_total{action}`, `hrms_leave_holds_resolved_total{outcome}`,
  `hrms_company_transfers_total{leave_mode}`, `hrms_hire_past_employment_refused_total`. See
  [REJOIN_RUNBOOK.md](REJOIN_RUNBOOK.md).

Secrets, all gitignored: `ops/.env` (`GRAFANA_ADMIN_PASSWORD`, user `admin`),
`ops/secrets/<environment>-metrics-token` (each equals that environment's
`HRMS_METRICS_TOKEN`), and `ops/alertmanager/alertmanager.yml` (receiver credentials;
template: `alertmanager.yml.example`).

```bash
docker compose -f ops/docker-compose.monitoring.yml up -d
```

Prometheus reads its configuration only at start-up: after editing `prometheus.yml` or
`alerts.yml`, run `docker restart hrms-prometheus`. The same goes for Alertmanager and Grafana.
Grafana dashboards come from the JSON files; edits made in the UI are not saved.

**Targets follow the environments.** Until the cut-over, the testing jobs point at the dev
server on 8015; the cut-over switches them to 8115. Production is scraped from
`ops/prometheus/targets/production.yml`, which is an empty list (`[]`) until production
exists, because a target that isn't running fires HrmsApiDown. To switch it on, copy
`production.yml.example` over it; Prometheus picks the change up without a restart.

## Health

| Endpoint | Meaning | Use it for |
|---|---|---|
| `GET /health`, `/health/live` | The process is up. Never touches the database | Container liveness (the Dockerfile `HEALTHCHECK` uses `/health`) |
| `GET /health/ready` | 200 when the database answers within 2 s and has this code's migrations (or newer). 503 with the reason otherwise | Load-balancer target health, the blackbox probe |

All three report `version`, `commit` and `built_at`.

---

# Alert runbook

Each alert in `ops/prometheus/alerts.yml` links here.

## HrmsApiDown
Prometheus can't scrape an API instance.
1. Check the container is running and its logs for a startup error. Production refuses to
   start on unsafe settings, and the error names the variable.
2. If it runs, check that the metrics token and the network path from Prometheus are right.

## HrmsNotReady
`/health/ready` is failing. Its JSON body says why:
- `"database": "unavailable"`: the database is down, unreachable or overloaded. Check it
  first; the API recovers on its own once it answers.
- `"schema": "migrations pending (…)"`: this code expects a newer migration. Run
  `alembic upgrade head` (the deploy should have done this before rolling out).

## HrmsPublicSiteDown
A public URL fails from outside while the local checks may still pass, so the problem is
usually between the user and the host.
1. Is the Cloudflare tunnel process running, and does its ingress point at the right port
   (docs/ENVIRONMENTS.md)?
2. Does the local address answer (`curl -sI http://127.0.0.1:<port>/`)? If not, see
   HrmsApiDown / HrmsNotReady.
3. Check Cloudflare's status page and the DNS records for both hostnames.

## HrmsHighErrorRate
More than 1% of requests end in 5xx.
1. Open Sentry: group by release. A new release at the top points at the deploy, so consider
   rolling back to the previous image tag.
2. Filter the logs by `level=ERROR`. `request_id` joins log lines to Sentry events.

## HrmsSlowResponses
p95 latency above 300 ms.
1. In Grafana, *Slowest routes* shows where the time goes, and *SQL time per request* shows
   whether it is the database.
2. Check *Connection pool* for saturation, and *SQL statements per request* for a route that
   has started looping.
3. Reproduce with the benchmark harness in `backend/perf/` (never against real data).

## HrmsDatabasePoolSaturated
An instance is using more than 80% of its connections. Requests queue for a connection and
latency climbs. Look for slow queries or long transactions (`pg_stat_activity`). If the load
is simply higher, add instances, or raise `HRMS_DATABASE_POOL_SIZE` within the database's
`max_connections` across *all* instances. A connection pooler (PgBouncer/RDS Proxy) helps
once there are many instances.

## HrmsQueryCountRegression
A route runs more than 50 SQL statements per request (p95). That is almost always a query
inside a loop (N+1) that grows with the data. Find the route in *SQL statements per request*.
In a development environment, set `HRMS_QUERY_METRICS=true` and read the `X-DB-Queries`
header, or run `backend/perf/bench_endpoints.py`, whose "max repeat" column names the
repeated statement. Batch it into one query and add a query-budget test, as in
`tests/test_leave_list.py`.

## HrmsLoginLockoutSpike
Many sign-in lockouts (429) or failures (401) in a short time: likely password guessing.
Check the access logs for `/v1/auth/login` by `client_ip`. The throttle is already stopping
the guesses (`core/throttle.py`); if one address dominates, block it at the proxy or WAF. A
burst spread over one company's addresses right after a password reset or data import is
more likely confused users. Contact the tenant.

## HrmsAccrualFailed
`POST /v1/leave/accrual/run` failed, so that month's leave was not credited. Find the error
in Sentry or the logs (`route=/v1/leave/accrual/run`), fix the cause, and run it again for
the same period. Accrual is idempotent: employees already credited for the month are skipped.

## HrmsScheduledActionsFailing
A scheduled personnel action (transfer, promotion, separation …) reached its date but could
not be applied, so it was parked as FAILED. Its `failure_reason` is visible in
`GET /v1/personnel-actions`. HR should correct and reschedule it, or cancel it. Until then the
employee's record does not reflect the change.

## HrmsJobStale

A scheduled job (`hrms.jobs`: `accrual` or `scheduled-actions`) hasn't succeeded for over
26 hours. `HrmsJobNeverRan` means no job has ever succeeded in this environment.

1. Is the jobs container running? `docker compose … ps jobs`, then `docker compose … logs jobs`.
2. Check the last runs:
   `SELECT job, status, started_at, tenants_ok, tenants_failed, detail FROM job_runs ORDER BY started_at DESC LIMIT 10;`
   - `detail` names the failing tenants and the error class.
   - The full traceback is in the jobs log, under the same tenant id.
3. Fix the cause, then run the job once by hand:
   `docker compose … run --rm jobs python -m hrms.jobs run accrual`.
   Accrual is idempotent per month, so running it again is safe.

### Local testing API scheduler

When testing still runs from `backend/` on port 8015 rather than from the deployed
Compose stack, the API does not start background jobs. Run a separate scheduler.
`deploy/hrms-local-jobs.service` is a systemd unit for this host's checkout at
`/home/aiserver/HRMS`, running as `aiserver`. Adjust those paths and the user for other hosts.
It reads `backend/.env`, runs a catch-up cycle immediately, then runs daily at
`HRMS_JOBS_DAILY_AT` (default 00:30 Asia/Kolkata). It retries failed cycles and restarts
after process exit or host reboot. Jobs credit leave under the configured policies,
apply due personnel actions, and flag overdue open attendance sessions.

After approval to enable those jobs on the testing database:

```bash
sudo install -m 0644 deploy/hrms-local-jobs.service /etc/systemd/system/hrms-local-jobs.service
sudo systemctl daemon-reload
sudo systemctl enable --now hrms-local-jobs.service
systemctl status hrms-local-jobs.service
journalctl -u hrms-local-jobs.service --since '10 minutes ago'
```

Verify new `SUCCEEDED` rows in `job_runs` and fresh
`hrms_job_last_success_timestamp_seconds` values after the next Prometheus scrape.
If testing switches to the deployed Compose stack, disable this local service and
use that stack's `jobs` service instead.

## HrmsIntegrationRejectRateHigh

A connected app's sync calls are being refused. Open Settings → Integrations → the app → *Sync
log*, filter by outcome `REJECTED`, and read the error codes:

- `UNKNOWN_DEPARTMENT` (or location, designation, company): map the values on the *Mappings*
  tab; the app's retries then succeed.
- `POSSIBLE_DUPLICATE`: resolve them on the *Possible duplicates* tab.
- `EMAIL_IN_USE`, `EMPLOYEE_CODE_IN_USE`: a data conflict between the two systems; fix the record
  in whichever system is wrong.
- `FAILED` outcomes are server errors: check Sentry with the `request_id`.

## HrmsIntegrationFeedLagging

The app stopped polling `/v1/integrations/events` while events are waiting. Check with the app's
team that their poller is running and its key is valid (the key's *last used* time is on the
*Keys* tab). Events are kept 30 days; after that the app must resync (it is told so with
`410 RESYNC_REQUIRED`).

## HrmsIntegrationExitsHeld

The app sent more exits in 24 hours than the company's safety valve allows. Open the app's
*Held exits*, check them with HR, and release or reject each. If the app is sending wrong exits,
pause the app first.

## HrmsIntegrationUnlinkedHires

Employees hired in HRMS were announced to the app more than 24 hours ago, and the app hasn't
linked them (it should call `PUT /v1/integrations/employees/{its id}` with the `employment_id`).
The *Not linked* list shows who. Usually the app's poller or its import of new joiners failed.

## HrmsApiKeyExpiring

Create a second key for the app (an app may have two), have the app's team switch to it, then
revoke the old one. Nothing stops working if the switch happens before the expiry date.

## HrmsApiKeyNewAddress

A connected app's key was used from an address it had never been used from. Open the app's *Sync
log*, filter by operation `NEW_IP`, and check the address with the app's team. Expected after a
server move. If not expected, revoke the key at once (Keys tab), create a new one, and set *Allowed
addresses* on it so the key works only from the app's servers.

## HrmsIntegrityViolations
The nightly `integrity` job (`backend/src/hrms/db/integrity.py`) found references the database
can't protect with a foreign key that point at nothing: change history, approvals, leave
movements, connected-app mappings or delegations whose target row is gone. The `check` label
names which. Every other reference has a real foreign key, so this means a row was deleted
outside the app (by hand, or by a script). To see which tenants are affected, run the check's
SQL from that file for each tenant as the app role, or the read-only
`scripts/db_preflight.py`. Restore the missing rows from a backup where possible; otherwise
record what was lost, then remove the dangling references.

## HrmsDatabaseMetricsMissing
`/metrics` exports database health (`hrms_db_*`) from a short query on every scrape, and the
query is failing or taking over two seconds. Check that the database is reachable from the API
and not overloaded (*Database time* on the HRMS database dashboard). Everything else on
`/metrics` keeps working meanwhile.

## HrmsLongTransaction
A transaction of the application has been open for over five minutes. It holds its locks the
whole time and stops vacuum from cleaning up after it. Find it with
`SELECT pid, now() - xact_start, state, left(query, 200) FROM pg_stat_activity
WHERE xact_start IS NOT NULL ORDER BY xact_start;` and end it with
`SELECT pg_cancel_backend(pid)` (or `pg_terminate_backend`). The app role's own limits
(`statement_timeout`, `idle_in_transaction_session_timeout`, set by `hrms.deploy migrate`)
should make this rare; a one-off script run as another role is the usual cause.

## HrmsDeadRowsPiling
Autovacuum isn't keeping up with a table: over 20 % of its rows are dead. Queries read the dead
rows too and the table grows. Check `pg_stat_user_tables` for when the table was last
autovacuumed. For a table that changes all day (the leave ledger, rate-limit windows), lower
its threshold: `ALTER TABLE <table> SET (autovacuum_vacuum_scale_factor = 0.02)` in a migration
(docs/database-hardening-plan.md, W9.3). A one-off `VACUUM (ANALYZE) <table>` helps meanwhile.

## HrmsSequentialScansOnLargeTable
A table of over 100,000 rows is being read by full scans at a high rate: some query has no
index to use. With `pg_stat_statements` (on in `deploy/compose.yml`), find it with
`SELECT calls, mean_exec_time, left(query, 200) FROM pg_stat_statements
ORDER BY total_exec_time DESC LIMIT 20;`, check its plan with `EXPLAIN (ANALYZE, BUFFERS)`, and
add the index in a migration (`migration_kit.index(..., concurrently=True)`).

## HrmsPartitionThresholdReached
`punches` or `attendance_days` passed 50 million rows or 20 GB, the point decision DB-D4 set for
partitioning them by month. Plan the change from docs/database-hardening-plan.md (W21): it
changes their primary keys, so it needs its own release and a maintenance window.

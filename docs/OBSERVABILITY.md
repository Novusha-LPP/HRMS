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

`ops/prometheus/prometheus.yml` is an example scrape configuration, and
`ops/prometheus/alerts.yml` holds the alert rules below. Import
`ops/grafana/dashboards/hrms-api.json` into Grafana (it asks for the Prometheus data source).

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

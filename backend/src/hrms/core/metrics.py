"""
Prometheus metrics, served at GET /metrics for a Prometheus scraper.

HTTP (every request, labelled by the matched route *template* — "/v1/employees/{id}", never
the literal URL — so label cardinality stays fixed):
  hrms_http_requests_total{method, route, status}
  hrms_http_request_duration_seconds{method, route}           histogram
  hrms_http_requests_in_progress{method}
  hrms_db_statements_per_request{method, route}               histogram
  hrms_db_time_per_request_seconds{method, route}             histogram
Sign-in outcomes are hrms_http_requests_total{route="/v1/auth/login"} by status:
200 success, 401 wrong credentials, 429 locked out, 403 suspended/inactive.

Database pool (sampled at scrape time):
  hrms_db_pool_size, hrms_db_pool_checked_out, hrms_db_pool_overflow, hrms_db_pool_limit

Jobs:
  hrms_leave_accrual_run_seconds                              histogram
  hrms_leave_accruals_credited_total
  hrms_scheduled_personnel_actions_total{outcome="applied|failed"}

Access: /metrics is for the scraper, not the internet. When HRMS_METRICS_TOKEN is set it
requires `Authorization: Bearer <token>` (Prometheus: `authorization.credentials`);
production refuses to start without one. Block the path at the proxy as well.

Workers: each process has its own counters. Run one uvicorn worker per container (the
Dockerfile default) and scrape each container, or set PROMETHEUS_MULTIPROC_DIR so
prometheus_client aggregates across workers (the pool gauges then describe only the
process that answered the scrape).
"""

import asyncio
import hmac
import os
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

from hrms.core import perf
from hrms.core.active_users import active_users
from hrms.core.config import settings

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
_STATEMENT_BUCKETS = (1, 2, 3, 5, 8, 12, 20, 35, 60, 100, 250, 1000)

HTTP_REQUESTS = Counter("hrms_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "hrms_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
)
HTTP_IN_PROGRESS = Gauge(
    "hrms_http_requests_in_progress",
    "HTTP requests being served",
    ["method"],
    multiprocess_mode="livesum",
)
DB_STATEMENTS = Histogram(
    "hrms_db_statements_per_request",
    "SQL statements run by one HTTP request",
    ["method", "route"],
    buckets=_STATEMENT_BUCKETS,
)
DB_TIME = Histogram(
    "hrms_db_time_per_request_seconds",
    "Time one HTTP request spent in SQL statements",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
)
ACCRUAL_RUN = Histogram(
    "hrms_leave_accrual_run_seconds",
    "Duration of one monthly leave accrual run",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
ACCRUALS_CREDITED = Counter(
    "hrms_leave_accruals_credited_total", "Leave balances credited by accrual runs"
)
SCHEDULED_ACTIONS = Counter(
    "hrms_scheduled_personnel_actions_total",
    "Scheduled personnel actions processed when due",
    ["outcome"],
)
INTEGRATION_REQUESTS = Counter(
    "hrms_integration_requests_total",
    "Calls from connected apps, by app code, operation and outcome",
    ["app", "operation", "outcome"],
)
INTEGRATION_NEW_IP = Counter(
    "hrms_integration_new_ip_total",
    "A connected app's key used from an address it had not been used from before",
    ["app"],
)
INTEGRATION_SESSIONS = Counter(
    "hrms_integration_sessions_total",
    "Employee session tokens requested by connected apps",
    ["app", "result"],
)
# A labelled series only appears once touched; start both at 0 so dashboards and increase()
# have a baseline before the first action is ever processed.
for _outcome in ("applied", "failed"):
    SCHEDULED_ACTIONS.labels(_outcome)


class _PoolCollector(Collector):
    """Connection-pool occupancy, read from SQLAlchemy at scrape time."""

    def collect(self):
        from hrms.core.database import engine

        pool = engine.sync_engine.pool
        for name, doc, read in (
            ("hrms_db_pool_size", "Configured pool size", "size"),
            ("hrms_db_pool_checked_out", "Connections in use", "checkedout"),
            ("hrms_db_pool_overflow", "Connections beyond the pool size", "overflow"),
        ):
            value = getattr(pool, read, None)
            if callable(value):
                yield GaugeMetricFamily(name, doc, value=float(value()))
        yield GaugeMetricFamily(
            "hrms_db_pool_limit",
            "Most connections this process may open (pool size + max overflow)",
            value=float(settings.database_pool_size + settings.database_max_overflow),
        )


REGISTRY.register(_PoolCollector())


class MetricsMiddleware:
    """Records the HTTP metrics above for every request (plain ASGI)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "")
        # Shared with QueryMetricsMiddleware, so statements are counted once per request.
        tally = perf.start_tally(keep_statements=perf.REQUEST_OBSERVER is not None)
        scope.setdefault("state", {})["query_tally"] = tally
        status = 500
        started = time.perf_counter()

        async def capture_status(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        HTTP_IN_PROGRESS.labels(method).inc()
        try:
            await self.app(scope, receive, capture_status)
        finally:
            HTTP_IN_PROGRESS.labels(method).dec()
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            principal = scope.get("state", {}).get("principal")
            if principal is not None and 200 <= status < 300:
                if route == "/v1/auth/logout":
                    active_users.remove(principal.tenant_id, principal.user_account_id)
                else:
                    active_users.record(principal.tenant_id, principal.user_account_id)
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_LATENCY.labels(method, route).observe(time.perf_counter() - started)
            DB_STATEMENTS.labels(method, route).observe(tally.count)
            DB_TIME.labels(method, route).observe(tally.seconds)
            perf.report(scope, tally)


router = APIRouter(include_in_schema=False)


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    if settings.metrics_token:
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied, f"Bearer {settings.metrics_token}"):
            raise HTTPException(401, "Metrics require the scrape token")
    registry = REGISTRY
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        registry.register(_PoolCollector())
    jobs = CollectorRegistry()
    jobs.register(_JobFreshness(await _last_job_successes()))
    jobs.register(_IntegrationHealth(await _integration_health()))
    jobs.register(_DatabaseHealth(await _database_health()))
    jobs.register(active_users)
    return Response(
        generate_latest(registry) + generate_latest(jobs), media_type=CONTENT_TYPE_LATEST
    )


async def _last_job_successes() -> list[tuple[str, float]]:
    """Each scheduled job's last success (hrms.jobs). A scrape must not fail with the database."""
    from sqlalchemy import text

    from hrms.core.database import AsyncSessionLocal

    try:
        async with asyncio.timeout(2), AsyncSessionLocal() as session:
            rows = await session.execute(
                text("""
                    SELECT job, EXTRACT(EPOCH FROM max(finished_at)) FROM job_runs
                    WHERE status = 'SUCCEEDED' GROUP BY job
                """)
            )
            return [(str(job), float(ts)) for job, ts in rows]
    except Exception:
        return []


class _JobFreshness(Collector):
    """
    hrms_job_last_success_timestamp_seconds{job_name}: alerted on when it falls a day behind.
    (Not `job`: Prometheus owns that label for the scrape target.)
    """

    def __init__(self, rows: list[tuple[str, float]]):
        self.rows = rows

    def collect(self):
        family = GaugeMetricFamily(
            "hrms_job_last_success_timestamp_seconds",
            "Unix time of the last successful run of each scheduled job",
            labels=["job_name"],
        )
        values = dict(self.rows)
        expected = {"accrual", "scheduled-actions"}
        if settings.mail_backend == "ses":
            expected.add("mail-delivery")
        for job in sorted(expected | values.keys()):
            family.add_metric([job], values.get(job, 0.0))
        yield family


async def _integration_health() -> list[dict]:
    """Per connected app: feed lag, held exits, unlinked hires, key expiry (numbers only)."""
    from sqlalchemy import text

    from hrms.core.database import AsyncSessionLocal

    try:
        async with asyncio.timeout(2), AsyncSessionLocal() as session:
            rows = await session.execute(text("SELECT * FROM integration_health()"))
            return [dict(r) for r in rows.mappings()]
    except Exception:
        return []


class _IntegrationHealth(Collector):
    """Gauges for the integration alerts in ops/prometheus/alerts.yml."""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def collect(self):
        labels = ["tenant", "app"]
        families = {
            "lag": GaugeMetricFamily(
                "hrms_integration_feed_lag_events",
                "Events available to a connected app that it has not confirmed reading",
                labels=labels,
            ),
            "read": GaugeMetricFamily(
                "hrms_integration_feed_last_read_timestamp_seconds",
                "Unix time a connected app last read its events feed (0 = never)",
                labels=labels,
            ),
            "held": GaugeMetricFamily(
                "hrms_integration_held_exits",
                "Exits a connected app sent that the safety valve is holding for HR",
                labels=labels,
            ),
            "unlinked": GaugeMetricFamily(
                "hrms_integration_unlinked_hires",
                "Employees hired in HRMS over 24 hours ago that the app has not linked",
                labels=labels,
            ),
            "expiry": GaugeMetricFamily(
                "hrms_integration_key_expiry_timestamp_seconds",
                "Unix time the app's soonest-expiring active key expires (0 = none expires)",
                labels=labels,
            ),
        }
        for row in self.rows:
            key = [row["tenant"], row["app"]]
            families["lag"].add_metric(key, float(row["feed_lag"]))
            read_at = row["feed_read_at"]
            families["read"].add_metric(key, read_at.timestamp() if read_at else 0.0)
            families["held"].add_metric(key, float(row["held_exits"]))
            families["unlinked"].add_metric(key, float(row["unlinked_hires"]))
            expiry = row["next_key_expiry"]
            families["expiry"].add_metric(key, expiry.timestamp() if expiry else 0.0)
        yield from families.values()


async def _database_health() -> dict:
    """
    Table sizes and churn, the oldest open transaction and the integrity job's findings
    (docs/database-hardening-plan.md, W9.4 and W7.3). Statistics only, no tenant data; read
    as the application's own role. A scrape must not fail with the database.
    """
    from sqlalchemy import text

    from hrms.core.database import AsyncSessionLocal

    try:
        async with asyncio.timeout(2), AsyncSessionLocal() as session:
            tables = (
                await session.execute(
                    text("""
                        SELECT relname AS table, n_live_tup AS live, n_dead_tup AS dead,
                               seq_scan, seq_tup_read, COALESCE(idx_scan, 0) AS idx_scan,
                               pg_total_relation_size(relid) AS bytes
                        FROM pg_stat_user_tables WHERE schemaname = 'public'
                    """)
                )
            ).mappings().all()
            database_bytes = await session.scalar(
                text("SELECT pg_database_size(current_database())")
            )
            # Only this role's sessions are visible to it, which are the ones that matter here.
            oldest = await session.scalar(
                text("""
                    SELECT COALESCE(max(EXTRACT(EPOCH FROM now() - xact_start)), 0)
                    FROM pg_stat_activity
                    WHERE datname = current_database() AND xact_start IS NOT NULL
                      AND pid <> pg_backend_pid()
                """)
            )
            findings = await session.scalar(
                text("""
                    SELECT findings FROM job_runs
                    WHERE job = 'integrity' AND status = 'SUCCEEDED'
                    ORDER BY finished_at DESC LIMIT 1
                """)
            )
            return {
                "tables": [dict(t) for t in tables],
                "database_bytes": float(database_bytes or 0),
                "oldest_transaction_seconds": float(oldest or 0),
                "findings": findings or {},
            }
    except Exception:
        return {}


class _DatabaseHealth(Collector):
    """Gauges for the database alerts and the HRMS database dashboard."""

    def __init__(self, health: dict):
        self.health = health

    def collect(self):
        if not self.health:
            return
        per_table: dict[str, GaugeMetricFamily | CounterMetricFamily] = {
            "bytes": GaugeMetricFamily(
                "hrms_db_table_size_bytes", "Table size including indexes", labels=["table"]
            ),
            "live": GaugeMetricFamily(
                "hrms_db_table_live_rows", "Estimated live rows", labels=["table"]
            ),
            "dead": GaugeMetricFamily(
                "hrms_db_table_dead_rows", "Dead rows waiting for vacuum", labels=["table"]
            ),
            "seq_scan": CounterMetricFamily(
                "hrms_db_table_seq_scans", "Sequential scans of the table", labels=["table"]
            ),
            "seq_tup_read": CounterMetricFamily(
                "hrms_db_table_seq_rows_read", "Rows read by sequential scans", labels=["table"]
            ),
            "idx_scan": CounterMetricFamily(
                "hrms_db_table_index_scans", "Index scans of the table", labels=["table"]
            ),
        }
        for row in self.health["tables"]:
            for key, family in per_table.items():
                family.add_metric([row["table"]], float(row[key] or 0))
        yield from per_table.values()
        yield GaugeMetricFamily(
            "hrms_db_size_bytes", "Size of the database", value=self.health["database_bytes"]
        )
        yield GaugeMetricFamily(
            "hrms_db_oldest_transaction_seconds",
            "Age of the oldest open transaction of the application's role",
            value=self.health["oldest_transaction_seconds"],
        )
        findings = GaugeMetricFamily(
            "hrms_integrity_violations",
            "Broken references the last integrity job found, by check (hrms.db.integrity)",
            labels=["check"],
        )
        for check, count in sorted(self.health["findings"].items()):
            findings.add_metric([check], float(count))
        yield findings

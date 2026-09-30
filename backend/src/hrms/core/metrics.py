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
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from hrms.core import perf
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
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

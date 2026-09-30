"""
Per-request database metrics — how many statements a request ran and how long they took.

Opt-in (HRMS_QUERY_METRICS=true): the response gets

    Server-Timing: db;dur=12.4;desc="7 queries", app;dur=18.9
    X-DB-Queries: 7

so a browser's network panel, the benchmark scripts in backend/perf/ and the query-budget
tests can all see what an endpoint costs. Counting happens in a SQLAlchemy cursor event
against a ContextVar holding a mutable per-request tally; SQLAlchemy's async greenlets run
in the calling task's context, so concurrent requests never see each other's counts.
Off, nothing is registered and the middleware is not installed — zero overhead.
"""

import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class QueryTally:
    count: int = 0
    seconds: float = 0.0
    statements: list[str] = field(default_factory=list)
    keep_statements: bool = False


_current: ContextVar[QueryTally | None] = ContextVar("hrms_query_tally", default=None)

# Set by the benchmark scripts (backend/perf/) to receive each request's full tally, statements
# included. None in the running app.
REQUEST_OBSERVER: Callable[[dict, QueryTally], None] | None = None


def start_tally(keep_statements: bool = False) -> QueryTally:
    """Begin counting in the current context (a request, or a test)."""
    tally = QueryTally(keep_statements=keep_statements)
    _current.set(tally)
    return tally


def current_tally() -> QueryTally | None:
    return _current.get()


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("hrms_query_start", []).append(time.perf_counter())


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    started = conn.info["hrms_query_start"].pop()
    tally = _current.get()
    if tally is None:
        return
    tally.count += 1
    tally.seconds += time.perf_counter() - started
    if tally.keep_statements:
        tally.statements.append(statement)


def instrument_engine(engine: AsyncEngine) -> None:
    """Count statements and SQL time into the current tally. Idempotent per engine."""
    sync_engine = engine.sync_engine
    if event.contains(sync_engine, "after_cursor_execute", _after_cursor_execute):
        return
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(sync_engine, "after_cursor_execute", _after_cursor_execute)


class QueryMetricsMiddleware:
    """Adds Server-Timing and X-DB-Queries headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # core/metrics.MetricsMiddleware, when installed, has already started this request's
        # tally; count into that one rather than a second.
        shared = scope.get("state", {}).get("query_tally")
        tally = shared or start_tally(keep_statements=REQUEST_OBSERVER is not None)
        started = time.perf_counter()

        async def send_with_metrics(message):
            if message["type"] == "http.response.start":
                total_ms = (time.perf_counter() - started) * 1000
                db_ms = tally.seconds * 1000
                timing = f'db;dur={db_ms:.1f};desc="{tally.count} queries", app;dur={total_ms:.1f}'
                headers = list(message.get("headers", []))
                headers.append((b"server-timing", timing.encode()))
                headers.append((b"x-db-queries", str(tally.count).encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_metrics)
        if shared is None:  # otherwise MetricsMiddleware owns it and reports it
            report(scope, tally)


def report(scope, tally: QueryTally) -> None:
    """Hand a finished request's tally to REQUEST_OBSERVER, if one is listening."""
    if REQUEST_OBSERVER is not None:
        REQUEST_OBSERVER(scope, tally)

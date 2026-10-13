"""
A reference client for HRMS's integrations API, for ERP and CRM developers to copy or adapt.
See docs/INTEGRATION_GUIDE.md. Requires `httpx`.

It shows the parts that are easy to get wrong:
- send only changed fields, with `source_updated_at`;
- retry 429 (after Retry-After), 5xx and timeouts with exponential backoff, never other 4xx;
- give every POST an Idempotency-Key, and reuse it on retry;
- poll the events feed from a stored cursor, handling 410 RESYNC_REQUIRED.

backend/tests/test_integration_reference_client.py runs it against the API in CI, so this file
can't drift from what the API actually does.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

RETRYABLE = {429, 500, 502, 503, 504}


class HrmsError(Exception):
    def __init__(self, status: int, body: dict[str, Any]):
        super().__init__(f"{status} {body.get('code')}: {body.get('detail')}")
        self.status = status
        self.code = body.get("code")
        self.body = body


class HrmsClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, *, max_attempts: int = 6):
        """`client` carries the base URL (e.g. httpx.AsyncClient(base_url="https://…"))."""
        self.http = client
        self.headers = {"X-API-Key": api_key}
        self.max_attempts = max_attempts

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        delay = 1.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await self.http.request(method, path, headers=headers, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == self.max_attempts:
                    raise
                await asyncio.sleep(delay + random.random() * delay / 2)
                delay = min(delay * 2, 300)
                continue
            if response.status_code in RETRYABLE and attempt < self.max_attempts:
                wait = float(response.headers.get("Retry-After", delay))
                await asyncio.sleep(wait + random.random() * delay / 2)
                delay = min(delay * 2, 300)
                continue
            return response
        raise AssertionError("unreachable")

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._call(method, path, **kwargs)
        body = response.json() if response.content else {}
        if response.status_code >= 400:
            raise HrmsError(response.status_code, body)
        return body

    # ─── Sending employees ───────────────────────────────────────────────────

    async def upsert(
        self, external_id: str, changed: dict[str, Any], *, changed_at: datetime | None = None
    ) -> dict[str, Any]:
        """Create or update one employee. Send only what changed in your system."""
        body = {**changed, "source_updated_at": (changed_at or datetime.now(UTC)).isoformat()}
        return await self._json("PUT", f"/v1/integrations/employees/{external_id}", json=body)

    async def link(self, external_id: str, employment_id: str) -> dict[str, Any]:
        """Link an employee hired in HRMS (from an employee.hired event) to your record."""
        return await self.upsert(external_id, {"employment_id": employment_id})

    async def exit(
        self, external_id: str, last_working_day: str, *, idempotency_key: str, reason: str = ""
    ) -> dict[str, Any]:
        """The same idempotency key on every retry of the same exit."""
        return await self._json(
            "POST",
            f"/v1/integrations/employees/{external_id}/exit",
            json={"last_working_day": last_working_day, "reason_code": reason or None},
            headers={"Idempotency-Key": idempotency_key},
        )

    async def session_for(self, external_id: str) -> str:
        """A bearer token to act as this employee on HRMS's self-service endpoints."""
        body = await self._json(
            "POST", "/v1/integrations/sessions", json={"external_id": external_id}
        )
        return body["access_token"]

    # ─── Reading changes ─────────────────────────────────────────────────────

    async def poll_once(
        self,
        cursor: str | None,
        handle: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        resync: Callable[[], Awaitable[None]] | None = None,
    ) -> str | None:
        """
        Handle every waiting event and return the cursor to store. Store it only after your
        handler succeeded; `handle` must be idempotent, since an event can come again after a
        crash. Call this every 30-60 seconds.
        """
        while True:
            params = {"limit": 500, **({"after": cursor} if cursor else {})}
            response = await self._call("GET", "/v1/integrations/events", params=params)
            if response.status_code == 410:  # too far behind the 30-day feed
                if resync is not None:
                    await resync()
                cursor = response.headers["X-Resync-Cursor"]
                continue
            body = response.json()
            if response.status_code >= 400:
                raise HrmsError(response.status_code, body)
            for event in body["events"]:
                await handle(event)
            cursor = body["next_cursor"]
            if not body["has_more"]:
                return cursor

    async def all_employees(self) -> list[dict[str, Any]]:
        """Everyone your app may see, for a first load or a resync."""
        out: list[dict[str, Any]] = []
        cursor = None
        while True:
            body = await self._json(
                "GET", "/v1/integrations/employees", params={"cursor": cursor} if cursor else {}
            )
            out += body["employees"]
            if not body["has_more"]:
                return out
            cursor = body["next_cursor"]

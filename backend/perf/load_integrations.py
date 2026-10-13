"""
Load test for the connected-app endpoints (sync, sessions and punches, the events feed), against
a synthetic perf-* tenant seeded by seed_scale.py in a throwaway database. See perf/README.md.

    uv run python perf/load_integrations.py .venv/bin/python . --slug perf-int

It starts its own 4-worker API on port 8099, so it never touches a running server.
RUSH_CONCURRENCY (default 50) sets how many employees punch at once.
"""

import asyncio
import os
import statistics
import subprocess
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8099"
ADMIN = ["admin@perf-int.perf.invalid", "PerfPassw0rd!"]  # seed_scale.py synthetic admin
results: dict[str, list[float]] = {}
SAMPLES: dict[int, str] = {}
errors: dict[str, dict[int, int]] = {}


def record(name, started, response):
    results.setdefault(name, []).append((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        errors.setdefault(name, {}).setdefault(response.status_code, 0)
        errors[name][response.status_code] += 1


async def run_pool(n, concurrency, job):
    queue = asyncio.Queue()
    for i in range(n):
        queue.put_nowait(i)

    async def worker():
        while not queue.empty():
            await job(queue.get_nowait())

    started = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return time.perf_counter() - started


def report():
    print(f"{'operation':<22}{'n':>6}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}  errors")
    for name, values in results.items():
        values = sorted(values)
        p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
        print(
            f"{name:<22}{len(values):>6}{statistics.median(values):>9.0f}{p95:>9.0f}"
            f"{values[-1]:>9.0f}  {errors.get(name, {})}"
        )


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=120) as admin:
        login = await admin.post(
            "/v1/auth/login", json={"identifier": ADMIN[0], "password": ADMIN[1]}
        )
        login.raise_for_status()
        admin.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        app = (
            await admin.post(
                "/v1/admin/integrations/apps",
                json={
                    "code": f"L{int(time.time()) % 100000}",
                    "name": "Load ERP",
                    "kind": "TWO_WAY",
                },
            )
        ).json()
        key = (
            await admin.post(
                f"/v1/admin/integrations/apps/{app['id']}/keys",
                json={
                    "name": "load",
                    "rate_limit_per_minute": 10000,
                    "scopes": [
                        "employees.sync",
                        "employees.read",
                        "sessions.issue",
                        "events.read",
                        "org.read",
                    ],
                },
            )
        ).json()["key"]
        bi = (
            await admin.post(
                "/v1/admin/integrations/apps",
                json={
                    "code": f"B{int(time.time()) % 100000}",
                    "name": "Load BI",
                    "kind": "READ_ONLY",
                },
            )
        ).json()
        bi_key = (
            await admin.post(
                f"/v1/admin/integrations/apps/{bi['id']}/keys",
                json={"name": "bi", "rate_limit_per_minute": 10000, "scopes": ["events.read"]},
            )
        ).json()["key"]
        employees = []
        offset = 0
        while True:
            page = (await admin.get(f"/v1/employees?limit=200&offset={offset}")).json()
            employees += page
            if len(page) < 200:
                break
            offset += 200
    print(f"{len(employees)} employees", flush=True)

    erp = httpx.AsyncClient(
        base_url=BASE,
        timeout=120,
        headers={"X-API-Key": key},
        limits=httpx.Limits(max_connections=100),
    )
    ref = (await erp.get("/v1/integrations/reference-data")).json()

    # Link everyone (go-live step), in chunks.
    t = time.perf_counter()
    for i in range(0, len(employees), 1000):
        chunk = employees[i : i + 1000]
        r = await erp.post(
            "/v1/integrations/employees/link",
            json={
                "dry_run": False,
                "records": [
                    {
                        "external_id": f"X-{e['employee_number']}",
                        "employee_code": e["employee_number"],
                    }
                    for e in chunk
                ],
            },
        )
        r.raise_for_status()
    print(f"link {len(employees)}: {time.perf_counter() - t:.1f}s")

    # Updates (contact change), 20 at a time.
    async def update(i):
        e = employees[i]
        started = time.perf_counter()
        r = await erp.put(
            f"/v1/integrations/employees/X-{e['employee_number']}",
            json={"mobile": f"9{i:09d}", "source_updated_at": "2026-10-12T10:00:00Z"},
        )
        record("upsert: update", started, r)

    took = await run_pool(400, 20, update)
    print(f"400 updates in {took:.1f}s")

    company = ref["companies"][0]
    dept = next(d["name"] for d in ref["departments"] if d["company_id"] == company["id"])
    loc = next(lo["name"] for lo in ref["locations"] if lo["company_id"] in (None, company["id"]))
    job = ref["designations"][0]["name"]

    async def create(i):
        started = time.perf_counter()
        r = await erp.put(
            f"/v1/integrations/employees/NEW-{i}",
            json={
                "first_name": "Load",
                "last_name": f"Test{i}",
                "company": company["name"],
                "department": dept,
                "location": loc,
                "designation": job,
                "hire_date": "2026-10-01",
                "employee_code": f"LT{uuid.uuid4().hex[:8].upper()}",
            },
        )
        record("upsert: create", started, r)

    took = await run_pool(200, 20, create)
    print(f"200 creates in {took:.1f}s")

    records = [
        {
            "external_id": f"BULK-{i}",
            "first_name": "Bulk",
            "last_name": f"B{i}",
            "company": company["name"],
            "department": dept,
            "location": loc,
            "designation": job,
            "hire_date": "2026-10-01",
            "employee_code": f"BK{uuid.uuid4().hex[:8].upper()}",
        }
        for i in range(200)
    ]
    started = time.perf_counter()
    r = await erp.post(
        "/v1/integrations/employees/bulk",
        json={"records": records},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    record("bulk of 200", started, r)

    # Morning rush: each employee gets a session and punches in, 50 at a time.
    rush = employees[:1000]

    async def morning(i):
        e = rush[i]
        started = time.perf_counter()
        s = await erp.post(
            "/v1/integrations/sessions", json={"external_id": f"X-{e['employee_number']}"}
        )
        record("session issue", started, s)
        if s.status_code != 200:
            return
        started = time.perf_counter()
        auth = {"Authorization": "Bearer " + s.json()["access_token"], "X-API-Key": ""}
        p = await erp.post("/v1/time/punches", json={"punch_type": "IN"}, headers=auth)
        if p.status_code == 409:  # already in from the seed: punch out instead
            started = time.perf_counter()
            p = await erp.post(
                "/v1/time/punches",
                json={"punch_type": "OUT", "confirm_long_day": True},
                headers=auth,
            )
            if p.status_code >= 400 and "detail" in p.json():
                SAMPLES.setdefault(p.status_code, p.json()["detail"][:120])
        record("punch via session", started, p)

    took = await run_pool(len(rush), int(os.environ.get("RUSH_CONCURRENCY", "50")), morning)
    print(
        f"morning rush: {len(rush)} sessions + punches in {took:.1f}s "
        f"({len(rush) / took:.0f} employees/s)"
    )

    # A BI-style reader draining the feed.
    after, pages = None, 0
    while True:
        started = time.perf_counter()
        r = await erp.get(
            "/v1/integrations/events",
            params={"after": after, "limit": 500} if after else {"limit": 500},
            headers={"X-API-Key": bi_key},
        )
        record("events page (500)", started, r)
        body = r.json()
        after, pages = body["next_cursor"], pages + 1
        if not body["has_more"]:
            break
    print(f"feed drained in {pages} page(s); sample errors: {SAMPLES}")
    await erp.aclose()
    report()


if __name__ == "__main__":
    if "--slug" in sys.argv:
        slug = sys.argv[sys.argv.index("--slug") + 1]
        if not slug.startswith("perf-"):
            sys.exit("Only synthetic perf-* tenants")
        ADMIN[0] = f"admin@{slug}.perf.invalid"
    env = dict(os.environ, HRMS_THROTTLE_ENABLED="false", HRMS_LOG_LEVEL="WARNING")
    server = subprocess.Popen(
        [
            sys.argv[1],
            "-m",
            "uvicorn",
            "hrms.main:app",
            "--port",
            "8099",
            "--workers",
            "4",
            "--log-level",
            "warning",
        ],
        env=env,
        cwd=sys.argv[2],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                if httpx.get(BASE + "/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        asyncio.run(main())
    finally:
        server.terminate()
        server.wait(timeout=30)

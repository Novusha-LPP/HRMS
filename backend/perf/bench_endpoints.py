"""
Per-endpoint cost: latency, SQL statement count, DB time and N+1 detection, per persona.

    HRMS_QUERY_METRICS=true uv run python perf/bench_endpoints.py --personas perf/out/perf-2k.json

Runs the real app in-process (httpx ASGITransport) against the database in the environment,
sequentially, so the numbers are the cost of one request with no contention. Concurrency is
measured separately (perf/locustfile.py). Writes <out>/<slug>-endpoints.{json,md}.

"max repeat" is how often the single most-repeated statement shape ran in one request — a
number that grows with the data (10, 200, 2000 …) is an N+1 loop.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("HRMS_QUERY_METRICS", "true")

import httpx  # noqa: E402

from hrms.core import perf  # noqa: E402
from hrms.main import app  # noqa: E402

PASSWORD = "PerfPassw0rd!"
TODAY = date.today()
MONTH_AGO = TODAY - timedelta(days=30)

# (label, method, path, personas, json body). {own} = the persona's own employment id,
# {report} = a system report id. Paths are formatted per persona.
ENDPOINTS = [
    (
        "auth/me (baseline)",
        "GET",
        "/v1/auth/me",
        ["employee", "hr_all", "dept_head", "hr_dept"],
        None,
    ),
    ("dashboard/employee", "GET", "/v1/dashboard/employee", ["employee"], None),
    ("dashboard/manager", "GET", "/v1/dashboard/manager", ["team_lead", "dept_head"], None),
    ("dashboard/hr", "GET", "/v1/dashboard/hr", ["hr_all", "hr_entity", "hr_dept"], None),
    ("dashboard/super-admin", "GET", "/v1/dashboard/super-admin", ["admin"], None),
    (
        "employees (page 50)",
        "GET",
        "/v1/employees",
        ["hr_all", "hr_entity", "hr_dept", "dept_head"],
        None,
    ),
    ("employees (page 200)", "GET", "/v1/employees?limit=200", ["hr_all"], None),
    ("persons (page 50)", "GET", "/v1/persons", ["hr_all"], None),
    ("persons/me", "GET", "/v1/persons/me", ["employee"], None),
    ("time/today", "GET", "/v1/time/today", ["employee"], None),
    (
        "time/attendance-days self 30d",
        "GET",
        f"/v1/time/attendance-days?from_date={MONTH_AGO}&to_date={TODAY}",
        ["employee"],
        None,
    ),
    (
        "time/attendance-days all 30d",
        "GET",
        f"/v1/time/attendance-days?from_date={MONTH_AGO}&to_date={TODAY}",
        ["hr_all", "dept_head"],
        None,
    ),
    (
        "time/daily-analysis",
        "GET",
        f"/v1/time/daily-analysis?work_date={TODAY - timedelta(days=1)}",
        ["hr_all", "hr_entity", "hr_dept"],
        None,
    ),
    ("time/overtime/pending", "GET", "/v1/time/overtime/pending", ["hr_all", "team_lead"], None),
    ("time/holidays", "GET", "/v1/time/holidays", ["employee"], None),
    ("leave/types", "GET", "/v1/leave/types", ["employee"], None),
    ("leave/balances self", "GET", "/v1/leave/balances", ["employee"], None),
    (
        "leave/applications self",
        "GET",
        "/v1/leave/applications?employment_id={own}",
        ["employee"],
        None,
    ),
    (
        "leave/applications all",
        "GET",
        "/v1/leave/applications",
        ["hr_all", "hr_entity", "dept_head", "team_lead"],
        None,
    ),
    (
        "leave/applications pending",
        "GET",
        "/v1/leave/applications?status=PENDING_L1",
        ["hr_all", "team_lead"],
        None,
    ),
    (
        "leave/applications/summary",
        "GET",
        "/v1/leave/applications/summary",
        ["hr_all", "hr_entity", "dept_head"],
        None,
    ),
    (
        "leave/applications inbox (decisions, 50)",
        "GET",
        "/v1/leave/applications?limit=50&status=PENDING_L1,PENDING_L2,PENDING_L3,"
        "CANCEL_PENDING_L1,CANCEL_PENDING_L2,CANCEL_PENDING_L3",
        ["hr_all", "team_lead"],
        None,
    ),
    ("leave/ledger self", "GET", "/v1/leave/ledger?employment_id={own}", ["employee"], None),
    (
        "leave/transactions self",
        "GET",
        "/v1/leave/transactions?employment_id={own}",
        ["employee"],
        None,
    ),
    ("corrections", "GET", "/v1/corrections", ["hr_all", "team_lead"], None),
    ("users", "GET", "/v1/users", ["admin"], None),
    ("roles", "GET", "/v1/roles", ["admin"], None),
    ("org/org-units", "GET", "/v1/org/org-units", ["hr_all"], None),
    ("org/legal-entities", "GET", "/v1/org/legal-entities", ["hr_all"], None),
    ("kyc/employees", "GET", "/v1/kyc/employees", ["hr_all"], None),
    ("kyc/summary", "GET", "/v1/kyc/summary", ["hr_all"], None),
    ("policies/effective self", "GET", "/v1/policies/employee/{own}/effective", ["employee"], None),
    ("reports list", "GET", "/v1/reports", ["hr_all"], None),
    ("report run (limit 1000)", "POST", "/v1/reports/{report}/run", ["hr_all"], {"limit": 1000}),
    ("onboarding/cases", "GET", "/v1/onboarding/cases", ["hr_all"], None),
]


def normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\$\d+|'[^']*'|\b\d+\b", "?", sql)).strip()[:160]


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--personas", required=True)
    p.add_argument("--runs", type=int, default=12)
    p.add_argument("--out", default="perf/out")
    p.add_argument("--only", help="regex on endpoint label")
    args = p.parse_args()
    meta = json.loads(Path(args.personas).read_text())
    slug = meta["slug"]

    observed: list = []
    perf.REQUEST_OBSERVER = lambda scope, tally: observed.append(tally)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://perf", timeout=300) as c:
        ctx = {}
        for persona, email in meta["personas"].items():
            r = await c.post("/v1/auth/login", json={"identifier": email, "password": PASSWORD})
            r.raise_for_status()
            h = {"Authorization": f"Bearer {r.json()['access_token']}"}
            me = (await c.get("/v1/auth/me", headers=h)).json()
            ctx[persona] = {"h": h, "own": me.get("employment_id")}
        reports = (await c.get("/v1/reports", headers=ctx["hr_all"]["h"])).json()
        report_id = reports[0]["id"] if reports else "none"

        results = []
        for label, method, path, personas, body in ENDPOINTS:
            if args.only and not re.search(args.only, label):
                continue
            for persona in personas:
                url = path.format(own=ctx[persona]["own"], report=report_id)
                lat, queries, db_ms, repeats, sizes, statuses = [], [], [], [], [], set()
                worst_stmt = ""
                for i in range(args.runs + 2):
                    observed.clear()
                    t = time.perf_counter()
                    r = await c.request(method, url, headers=ctx[persona]["h"], json=body)
                    elapsed = (time.perf_counter() - t) * 1000
                    statuses.add(r.status_code)
                    if i < 2:
                        continue  # warm-up
                    tally = observed[-1]
                    counts = Counter(normalise(s) for s in tally.statements)
                    stmt, rep = counts.most_common(1)[0] if counts else ("", 0)
                    lat.append(elapsed)
                    queries.append(tally.count)
                    db_ms.append(tally.seconds * 1000)
                    repeats.append(rep)
                    sizes.append(len(r.content))
                    worst_stmt = stmt
                lat.sort()
                row = {
                    "endpoint": label,
                    "persona": persona,
                    "status": sorted(statuses),
                    "p50_ms": round(statistics.median(lat), 1),
                    "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)], 1),
                    "queries": round(statistics.mean(queries), 1),
                    "db_ms": round(statistics.mean(db_ms), 1),
                    "db_share": round(statistics.mean(db_ms) / statistics.median(lat), 2),
                    "max_repeat": max(repeats),
                    "repeated_stmt": worst_stmt if max(repeats) > 3 else "",
                    "kb": round(statistics.mean(sizes) / 1024, 1),
                }
                results.append(row)
                print(
                    f"{label:34} {persona:10} {row['status']} p50 {row['p50_ms']:>8} ms  "
                    f"p95 {row['p95_ms']:>8}  q {row['queries']:>6}  db {row['db_ms']:>7} ms  "
                    f"rep {row['max_repeat']:>5}  {row['kb']:>7} KB",
                    flush=True,
                )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{slug}-endpoints.json").write_text(json.dumps(results, indent=2))
    lines = [
        "| endpoint | persona | status | p50 ms | p95 ms | queries | DB ms | max repeat | KB |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: -r["p50_ms"]):
        lines.append(
            f"| {r['endpoint']} | {r['persona']} | {','.join(map(str, r['status']))} | "
            f"{r['p50_ms']} | {r['p95_ms']} | {r['queries']} | {r['db_ms']} | "
            f"{r['max_repeat']} | {r['kb']} |"
        )
    (out / f"{slug}-endpoints.md").write_text("\n".join(lines) + "\n")
    print(f"-> {out / (slug + '-endpoints.md')}")


if __name__ == "__main__":
    asyncio.run(main())

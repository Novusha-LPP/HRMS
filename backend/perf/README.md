# Performance harness

Measures what the API costs per request and under load, against **synthetic data in a
throwaway database**. Never point any of this at a database holding real employee data —
`seed_scale.py` refuses to run if it finds a tenant whose slug doesn't start with `perf-`.

| File | What it does |
|---|---|
| `seed_scale.py` | Generates a tenant of N employees: 4 companies, 100 org units, 3-level reporting lines, logins for every scope pattern, months of attendance history, and leave accruals and applications created through the real API |
| `bench_endpoints.py` | Per endpoint and persona: p50/p95 latency, SQL statement count, DB time, and N+1 detection ("max repeat") |
| `locustfile.py` | Concurrent working-day mix: morning punch rush, employee self-service, managers, HR |
| `src/hrms/core/perf.py` | `HRMS_QUERY_METRICS=true` adds `Server-Timing` / `X-DB-Queries` headers to every response |

All synthetic accounts use the password `PerfPassw0rd!`. The personas are written to
`perf/out/<slug>.json`, which is gitignored.

## Run it

```bash
# 1. A private Postgres (unix socket only), with pg_stat_statements
initdb -D /tmp/pgperf/data -U hrms --auth=trust
pg_ctl -D /tmp/pgperf/data -l /tmp/pgperf/log -o "-c listen_addresses='' \
  -c unix_socket_directories=/tmp/pgperf -c port=54329 \
  -c shared_preload_libraries=pg_stat_statements -c max_connections=300" start
psql -h /tmp/pgperf -p 54329 -U hrms -d postgres -c "CREATE DATABASE hrms_perf"

# 2. Point the app at it. Environment variables override backend/.env.
export HRMS_DATABASE_URL="postgresql+asyncpg://hrms@:54329/hrms_perf?host=/tmp/pgperf"
export HRMS_APP_DATABASE_URL="postgresql+asyncpg://hrms_app@:54329/hrms_perf?host=/tmp/pgperf"
export HRMS_THROTTLE_ENABLED=false HRMS_QUERY_METRICS=true
uv run alembic upgrade head

# 3. Seed, then measure
uv run python perf/seed_scale.py --slug perf-2k --employees 2000 --months 6
uv run python perf/bench_endpoints.py --personas perf/out/perf-2k.json
uv run uvicorn hrms.main:app --port 8099 --workers 4 &
PERF_PERSONAS=perf/out/perf-2k.json uv run --with locust locust -f perf/locustfile.py \
  --host http://127.0.0.1:8099 --headless -u 300 -r 20 -t 3m
```

Local numbers run over a unix socket at about 0.1 ms per round trip. A managed database
across the network is typically 0.3–1 ms per round trip, so a request's statement count
matters more in production than these local latencies suggest.

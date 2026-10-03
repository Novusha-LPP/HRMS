# Environments: local, testing, production

HRMS runs in exactly three environments. Every setting that differs between them is in
one place: `HRMS_ENVIRONMENT` and that environment's env file.

| | **local** | **testing** | **production** |
|---|---|---|---|
| What it is | A developer's machine | The shared test deployment | The live deployment |
| URLs | `localhost:5173` → `localhost:8015` | `testinghrms.alvision.in` → `hrmsapi.alvision.in` | To be decided |
| Data | Demo or synthetic data only | **Real employee data** (imported tenants) | Real employee data |
| Runs from | The working tree (`npm run dev`, `uvicorn --reload`) | Released images (`deploy/compose.yml`) | The same released images |
| Settings | `backend/.env`, `frontend/.env` | `deploy/env/testing.env` | `deploy/env/production.env` |
| Safeguards | Relaxed | **All of them** | All of them |

**Testing is not a sandbox.** It holds real people's Aadhaar, PAN and bank details, so it
gets every production safeguard. The application enforces this at start-up
(`core/config.py`, tested in `tests/test_environments.py`). A testing or production instance
refuses to start with any of these:

- `HRMS_DEBUG=true` (error responses would carry tracebacks);
- the default signing secret, or one shorter than 32 characters;
- either published database password (`hrms`, `hrms_app_dev_password`);
- `/metrics` without `HRMS_METRICS_TOKEN`;
- a CORS origin that isn't `https://`.

On testing and production, the API docs (`/docs`, `/redoc`, `/openapi.json`) are off unless
`HRMS_API_DOCS_ENABLED=true`. The demo seeders (`seed_demo.py`,
`populate_tenant_operations.py`) refuse to run there. The web app shows a **Testing
environment** badge on every page of the testing site.

## How a change reaches production

```
commit ─► CI (checks.yml) ─► merge to main ─► release-please PR ─► release vX.Y.Z
                                                                      │
                     images ghcr.io/novusha-lpp/hrms/{api,web}:X.Y.Z ◄┘
                                     │
          deploy X.Y.Z to testing ─► verify ─► deploy the SAME X.Y.Z to production
```

- **Build once, deploy many.** The web image reads its API address and Sentry settings at
  start-up, from `config.js` (`frontend/src/lib/runtimeConfig.ts`,
  `deploy/web/40-hrms-config.sh`). The bytes that were tested are therefore the bytes that
  go live.
- **CI proves the deployment, not just the code.** The `deploy-smoke` job runs
  `deploy/smoke-test.sh`. It starts the whole stack from freshly built images and checks:
  - health, hidden API docs, the metrics token and CORS;
  - that the published database password is refused;
  - that the scheduled jobs run;
  - the web `config.js`;
  - that a backup is private and actually restores.
- **Nothing reaches a deployed environment from the working tree.** If you edit a file on
  the server, nothing changes until a release is deployed.

## Deploying

On the host, with the repository checked out at the release tag:

```bash
# First time only: create the env file from the template and fill in the secrets.
cp deploy/env/testing.env.example deploy/env/testing.env
#   every secret: openssl rand -hex 32   (URL-safe, no quoting needed)
sudo mkdir -p /srv/hrms-backups

# Every deploy: set HRMS_VERSION in the env file to the release, then
docker compose --env-file deploy/env/testing.env -f deploy/compose.yml pull
docker compose --env-file deploy/env/testing.env -f deploy/compose.yml up -d --wait
```

`up` runs the services in this order:
1. **db**: Postgres, with password authentication for every connection and no published port.
2. **migrate**: `python -m hrms.deploy migrate`. It applies the migrations, then sets the
   `hrms_app` role's password from `HRMS_APP_ROLE_PASSWORD`. If this step fails, the API
   doesn't start.
3. **api**: several workers (`WEB_CONCURRENCY`) on `127.0.0.1:$HRMS_API_PORT`, restarted
   automatically if it crashes.
4. **jobs**: `python -m hrms.jobs schedule`. Every day at `HRMS_JOBS_DAILY_AT` (tenant time),
   it runs the leave accrual and the due personnel actions.
5. **web**: nginx serving the app on `127.0.0.1:$HRMS_WEB_PORT`.
6. **backup**: a nightly `pg_dump`, plus the KYC files, into `HRMS_BACKUP_DIR`.

**Rolling back:** set `HRMS_VERSION` to the previous release and run `up -d` again.
Migrations are additive within a release series (docs/RELEASING.md). If a release did
change the schema, restore the backup taken before it.

**Both environments on one host:** they are separate compose projects (`hrms-testing`,
`hrms-production`). Each has its own database, volumes, network and ports: testing uses
8115/8180 and production 8215/8280, all bound to localhost.

### Pointing the Cloudflare tunnel at it

The tunnel's ingress rules decide which local port each hostname reaches. For testing:

```yaml
ingress:
  - hostname: testinghrms.alvision.in
    service: http://127.0.0.1:8180   # web container (was the Vite dev server on 5173)
  - hostname: hrmsapi.alvision.in
    service: http://127.0.0.1:8115   # api container (was uvicorn --reload on 8015)
```

## Moving the current testing site onto this

Today `testinghrms` / `hrmsapi` are served by the **dev servers from the working tree**
(Vite on 5173 and `uvicorn --reload` on 8015), against the `hrms-db-1` database. The move:

1. **Back up the current database first:**
   ```bash
   docker exec hrms-db-1 pg_dump -U hrms -Fc hrms > /srv/hrms-backups/pre-cutover.dump
   chmod 600 /srv/hrms-backups/pre-cutover.dump
   ```
2. Tag and release the current `main` (docs/RELEASING.md), then fill in
   `deploy/env/testing.env`.
3. Start the stack once so its database exists, then stop the services that use it:
   ```bash
   docker compose --env-file deploy/env/testing.env -f deploy/compose.yml up -d --wait
   docker compose --env-file deploy/env/testing.env -f deploy/compose.yml stop api jobs backup
   ```
4. Restore the dump into the new database. Then run `migrate` again, which sets the
   app-role password:
   ```bash
   docker compose --env-file deploy/env/testing.env -f deploy/compose.yml run --rm \
     --entrypoint /bin/sh -v /srv/hrms-backups:/import:ro backup \
     /backup/restore.sh /import/pre-cutover.dump
   docker compose --env-file deploy/env/testing.env -f deploy/compose.yml up -d --wait
   ```
5. Switch the tunnel to 8180/8115 (above) and check the site.
6. Stop the dev servers. Keep `hrms-db-1` for a week as a fallback, then remove it.

Local development keeps working as before: the dev servers and `hrms-db-1`, with
`HRMS_ENVIRONMENT=local`.

## Backups

- **What:** nightly at `HRMS_BACKUP_AT`. The database is dumped in `pg_dump` custom format;
  each dump is verified with `pg_restore --list` before it counts. The KYC document store is
  tarred alongside.
- **Retention:** `HRMS_BACKUP_KEEP_DAYS` days, in `HRMS_BACKUP_DIR/<environment>/`.
- **Who can read them:** root only (mode 600). They contain every employee's personal data.
- **Off-site, required:** a copy on the same disk is not a backup. Have root's cron sync
  `HRMS_BACKUP_DIR` to storage that is somewhere else, for example
  `rclone sync /srv/hrms-backups remote:hrms-backups`. Use encrypted storage.
- **Monitoring:** `deploy/backup/check-backups.sh /srv/hrms-backups/testing` exits non-zero
  when the last good backup is more than 26 h old. Run it from root's cron and alert on
  failure.

### Restore drill (monthly)

Restore the latest dump into a scratch database, check it, and drop it. CI does this on
every change (`deploy/smoke-test.sh`); doing it on real dumps proves those dumps are good.

```bash
D=$(sudo sed -n 1p /srv/hrms-backups/testing/latest)
docker exec hrms-testing-db-1 createdb -U hrms restore_drill
sudo cat /srv/hrms-backups/testing/$D | docker exec -i hrms-testing-db-1 \
  pg_restore --no-owner --exit-on-error -U hrms -d restore_drill
docker exec hrms-testing-db-1 psql -U hrms -d restore_drill -c "select version_num from alembic_version"
docker exec hrms-testing-db-1 dropdb -U hrms restore_drill
```

## Encryption at rest

These are stored encrypted with AES-256-GCM, in every environment:
- **Identifiers:** Aadhaar, PAN, UAN, PF, ESI, passport, driving licence, voter ID and bank
  account numbers, plus the number on each uploaded document (`core/field_crypto.py`).
- **Uploaded files:** every KYC scan (`core/document_store.py`).

The API decrypts them only for the people allowed to see them. A database dump, a backup
or the storage volume on its own reveals nothing.

- **Keys:** `HRMS_FIELD_ENCRYPTION_KEYS`, as `<id>:<32 bytes base64url>`. Testing and
  production each need their own key; they refuse to start without one, or with the local
  development key.
- **Losing the key loses the data.** Keep each environment's key in the password manager,
  separately from the backups. A backup is only restorable together with its key.
- **Rotation:** put a new key first, keep the old one after it, then deploy. The `migrate`
  step re-encrypts every value and file with the new key. Remove the old key only after
  `docker compose … run --rm jobs python -m hrms.deploy encrypt-pii --check` reports 0.
- **Existing data** (rows and files from before encryption) is still readable as it is.
  The `migrate` step encrypts it on the first deploy, which covers the testing cut-over.
- **Uploaded files** can live on local disk (`HRMS_DOCUMENT_STORAGE=local`, the default) or
  in S3 (`HRMS_DOCUMENT_STORAGE=s3` with `HRMS_DOCUMENT_S3_BUCKET`, plus
  `HRMS_DOCUMENT_S3_ENDPOINT_URL` for S3-compatible stores). Use S3 for production, with a
  versioned bucket that blocks public access.

## Scheduled jobs

`python -m hrms.jobs` records every run in `job_runs`. `/metrics` exports
`hrms_job_last_success_timestamp_seconds{job_name}`, and the `HrmsJobStale` alert fires
when a job hasn't succeeded for 26 hours.

| Job | What it does | Notes |
|---|---|---|
| `accrual` | Credits this month's leave to every eligible employee | Recorded as `SYSTEM_ACTOR`. Idempotent, so running it daily is safe |
| `scheduled-actions` | Applies personnel actions whose effective date has arrived | Requests also apply them; this covers days when nobody signs in |

Running a job by hand: `docker compose … run --rm jobs python -m hrms.jobs run accrual`.
The exit code is 1 if any tenant failed. A failing tenant doesn't stop the others.

## Monitoring

`ops/docker-compose.monitoring.yml` runs Prometheus, Alertmanager and Grafana, all bound to
localhost only. Before starting them:
- write each environment's `HRMS_METRICS_TOKEN` to `ops/secrets/testing-metrics-token` and
  `ops/secrets/production-metrics-token`;
- copy `ops/alertmanager/alertmanager.yml.example` to `alertmanager.yml` and set the
  recipients;
- set `GRAFANA_ADMIN_PASSWORD`.

Until production is deployed, comment out the `hrms-api-production` scrape job. Otherwise
`HrmsApiDown` fires for it.

## Still to do for 9/10

These are tracked in the stability plan. They aren't environment work, but they decide
whether testing and production are safe to run:

- **Encryption is built:** identifiers and files (see "Encryption at rest"). The testing
  data gets encrypted at the cut-over.
- **Production KYC files on S3:** the backend is built; it needs a bucket and credentials.
- **Off-site backup copy and the backup-age check**, set up on the host (see Backups).
- Router test coverage for attendance, leave and onboarding, and end-to-end UI tests.

# HRMS — Real environment map

**One page that answers: what settings and secrets does HRMS use, where is each one stored,
and what does it connect to?** Written 2026-10-21 from the files actually on this machine.

> 🔒 **This file contains no secret values** — only names, locations and lengths. Keep it that
> way. Never paste a password, key or token into it.

**Contents**
0. [Start here: where to put what (new people)](#start-here-where-to-put-what-new-people)
1. [Quick answers](#1-quick-answers)
2. [The three environments](#2-the-three-environments)
3. [How it all connects](#3-how-it-all-connects)
4. [Every file that holds settings or secrets (this machine)](#4-every-file-that-holds-settings-or-secrets-this-machine)
5. [Every secret explained](#5-every-secret-explained)
6. [Other settings you will see](#6-other-settings-you-will-see)
7. [What lives outside this machine](#7-what-lives-outside-this-machine)
8. [CI, releases, monitoring and backups](#8-ci-releases-monitoring-and-backups)
9. [Problems to fix](#9-problems-to-fix)
10. [How-to: change or rotate things](#10-how-to-change-or-rotate-things)
11. [Glossary](#11-glossary)

Related docs: [ENVIRONMENTS.md](ENVIRONMENTS.md) · [AWS_TESTING_CICD.md](AWS_TESTING_CICD.md) ·
[EC2_TESTING_DEPLOYMENT_GUIDE.md](EC2_TESTING_DEPLOYMENT_GUIDE.md) · [OBSERVABILITY.md](OBSERVABILITY.md) ·
[HISTORY_MIGRATION_RUNBOOK.md](HISTORY_MIGRATION_RUNBOOK.md)

---

## Start here: where to put what (new people)

**The rule:** real settings and secrets live **only** in git-ignored `.env`-style files on a
machine, or in GitHub/AWS. Git only ever contains the `*.example` templates. If a file is
named `.env`, `*.env` or sits in `ops/secrets/`, never commit it and never paste it in chat.

### A. Run HRMS on your own computer (local)

| Step | What to do |
|---|---|
| 1 | Start the database: `docker compose up -d db` (Postgres on `127.0.0.1:5432`, dev password; local only). |
| 2 | `cp backend/.env.example backend/.env` — works as-is for local (dev key and passwords are public and only accepted when `HRMS_ENVIRONMENT=local`). |
| 3 | `cp frontend/.env.example frontend/.env` — leave `VITE_API_URL=http://localhost:8015`. |
| 4 | From `backend/`: `uv sync`, `uv run alembic upgrade head`, then `uv run uvicorn hrms.main:app --reload --port 8015` (Swagger at <http://localhost:8015/docs>). |
| 5 | Start the web app (from `frontend/`): `npm install && npm run dev` → <http://localhost:5173>. |
| 6 | `chmod 600 backend/.env`, then create the first platform admin: `uv run python scripts/seed_platform_admin.py you@example.com`. |

Only use **demo or synthetic data** locally unless you have been told otherwise.

### B. Where each kind of value goes

| You have… | Put it in… | Never in… |
|---|---|---|
| A local setting (port, debug, local DB URL) | `backend/.env` or `frontend/.env` | git |
| A **testing** secret (DB password, signing key, encryption key, metrics token) | GitHub → Settings → Environments → **testing** → *Secrets*; CI copies it to the server | `deploy/aws/*.env` committed, chat, tickets |
| A **testing** public value (URL, bucket name, region, CORS) | the same GitHub environment → *Variables* | — |
| A **production** secret | `deploy/env/production.env` (copied from the `.example`) on the production host, plus a password manager | git |
| The **field-encryption key** | password manager **and** the environment's secret store (two places, always) | a single laptop |
| Monitoring tokens / Grafana password | `ops/secrets/*`, `ops/.env` | git |
| ERP/CRM logins for migration | a password manager (not `credential.md`) | the repo folder |
| AWS access | nowhere: CI uses GitHub OIDC, the server uses its instance role | any file |

### C. How a change gets live (testing)

1. Merge/push to the **`testing`** branch.
2. GitHub Actions runs tests, builds the two Docker images, packages the settings, and tells the
   EC2 server (through AWS Systems Manager) to deploy.
3. The server saves the settings in `/etc/hrms/` (root only), runs a database check and the
   migrations, then restarts the API, the daily-jobs worker and the web container.
4. Cloudflare forwards `testhrms.alvision.in` / `testhrmsapi.alvision.in` to those containers.
   Check <https://testhrmsapi.alvision.in/health> — its `commit` must match what you pushed.

**Nothing you edit in the working tree reaches testing or production.** Only a deploy does.

### D. Which website am I looking at?

| URL | What it really is | Database |
|---|---|---|
| `http://localhost:5173` | your own Vite dev server | local Docker Postgres |
| `https://testinghrms.alvision.in` / `https://hrmsapi.alvision.in` | **the dev servers on the developer machine** (Vite `:5173`, uvicorn `:8015`) published through a Cloudflare tunnel; `/health` shows `commit: unknown` | the developer machine's local Postgres |
| `https://testhrms.alvision.in` / `https://testhrmsapi.alvision.in` | **the AWS deployment** (EC2 + RDS + S3); `/health` shows a real commit | AWS RDS `hrms_testing` |

---

## 1. Quick answers

| I need to know… | Answer |
|---|---|
| Where are my **local** settings? | `backend/.env` and `frontend/.env` |
| Where are the **testing (live)** settings? | On the EC2 server: `/etc/hrms/testing.runtime.env`, `testing.migrate.env`, `testing.deploy.env`. Source of truth: GitHub → Environments → **testing** (secrets + variables). A copy is also on this machine in `deploy/aws/testing.*.env`. |
| Where is the **production** config? | Not deployed yet. Template: `deploy/env/production.env` (placeholders for hostnames) |
| Where is the **live database**? | AWS RDS `hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com`, database `hrms_testing` |
| Where is the **local database**? | Docker container `hrms-db-1`, `127.0.0.1:5432`, database `hrms` |
| Where are **uploaded documents**? | Testing: S3 bucket `hrms-testing-docs`. Local: `backend/storage/` |
| Which key **encrypts Aadhaar/PAN/bank data**? | `HRMS_FIELD_ENCRYPTION_KEYS` — back it up, losing it loses the data |
| Which key **signs logins**? | `HRMS_SECRET_KEY` |
| Where are the **ERP/CRM logins** (Suraj, RABS)? | `credential.md` (plain text, git-ignored) |
| Where is **Grafana's** password? | `ops/.env` (`GRAFANA_ADMIN_PASSWORD`, user `admin`) |
| Which server runs testing? | EC2 `i-0d7abe00772ca6669`, region `ap-south-1` |
| What is **not** stored anywhere? | AWS access keys (CI uses GitHub OIDC, EC2 uses an instance role) |

---

## 2. The three environments

| | **Local** (this machine) | **Testing** (live, REAL data) | **Production** |
|---|---|---|---|
| Status | running | running | not deployed yet |
| Website | `http://localhost:5173` (Vite; `:3000` also listening) | `https://testhrms.alvision.in` | `hrms.example.com` (placeholder) |
| API | `http://localhost:8015` | `https://testhrmsapi.alvision.in` | `api.hrms.example.com` (placeholder) |
| Database | Docker Postgres 16, `127.0.0.1:5432` | AWS RDS, db `hrms_testing`, TLS `verify-full` | planned: own DB |
| Documents | `backend/storage/` | S3 `hrms-testing-docs` (ap-south-1) | template says `local`; S3 recommended |
| Runs from | working tree, `uvicorn --reload` | released Docker images on EC2 | same images as testing |
| Host ports (127.0.0.1) | 8015 API, 5173 web | 8115 API, 8180 web (Cloudflare points here) | 8215 API, 8280 web |
| Settings | `backend/.env`, `frontend/.env` | `/etc/hrms/testing.*.env` | `deploy/env/production.env` |
| Debug | on (`HRMS_DEBUG=true`) | off, enforced | off, enforced |

> Testing is **not a sandbox** — it holds real employee Aadhaar, PAN and bank data and gets
> every production safeguard. The app refuses to start there with weak secrets, debug on,
> development passwords, missing encryption keys, or non-https CORS origins.

ℹ️ **Two "testing" URL pairs exist, and they are different systems** (see *Start here → D*).
The `testinghrms…`/`hrmsapi…` pair is the developer machine's dev servers through a Cloudflare
tunnel (`~/.cloudflared/config3.yml`, tunnel `rabs`); the `testhrms…`/`testhrmsapi…` pair is the
AWS deployment. That is why `backend/.env` allows both sets of origins and `frontend/.env`
points at `hrmsapi.alvision.in`: remote browsers loading `testinghrms.alvision.in` must reach the API
through its public address.

---

## 3. How it all connects

### Live testing

```
 you: git push  (branch "testing")
            │
            ▼
 GitHub Actions  .github/workflows/deploy-testing-ec2.yml
   • reads GitHub Environment "testing": 6 secrets + public variables
   • logs in to AWS with OIDC role (no stored AWS keys)
   • builds API + web images → ECR (hrms-testing-api, hrms-testing-web)
   • writes the 3 env files + compose.yml into a .tar.gz → private S3 artifact bucket
            │  AWS Systems Manager "Run Command"  (deploy/aws/send-command.py)
            ▼
 EC2  i-0d7abe00772ca6669
   /opt/hrms/testing/releases/<commit>-<run>/deploy.sh   (runs as root)
   → installs /etc/hrms/testing.{runtime,migrate,deploy}.env  (root, mode 600)
   → checks them (validate.py) → checks the database (database-preflight.py)
   → runs migrations → starts  api · jobs · web   (Docker Compose)
            │
 Cloudflare tunnel ──► 127.0.0.1:8180 (web)    127.0.0.1:8115 (api)
            │
 api / jobs ──TLS──────────────► AWS RDS  hrms_testing
                                   login "hrms_app"       runtime queries (row-level security)
                                   login "hrms_platform"  platform console only
                                   owner login            migrations only (migrate.env)
 api / jobs ──EC2 instance role─► S3  hrms-testing-docs   (documents, encrypted by the app)
 web ──/config.js──► tells the browser which API URL to call
```

### Local development

```
Browser :5173 (Vite) ──VITE_API_URL──► uvicorn :8015 ──► Docker Postgres :5432
        frontend/.env                    backend/.env       container hrms-db-1
                                         files → backend/storage/
```

### Monitoring (all on this machine, Docker, bound to 127.0.0.1)

```
Prometheus :9090 ──bearer token (ops/secrets/*-metrics-token)──► API /metrics
   ├── Alertmanager :9093 (email/Slack, config in ops/alertmanager/alertmanager.yml)
   ├── Grafana :3100 (admin password in ops/.env)
   ├── blackbox :9115 (probes the public testing URLs)
   └── node-exporter :9100
```

### Why three database logins?

| Login | Used by | Why |
|---|---|---|
| owner (`postgres`/RDS master-style user) | migrations only | needs rights to change tables |
| `hrms_app` | the running API and jobs | cannot bypass row-level security, so one company can never read another's data |
| `hrms_platform` | the platform admin console only | the only login that can see platform admins and platform audit |

---

## 4. Every file that holds settings or secrets (this machine)

All files below are **git-ignored and untracked** (checked with `git check-ignore`). "Real"
means real values, not examples.

| File | Env | What is inside | Mode |
|---|---|---|---|
| `backend/.env` | local | 3 DB URLs → local Docker Postgres, `HRMS_SECRET_KEY`, `HRMS_FIELD_ENCRYPTION_KEYS`, `HRMS_DEBUG=true`, `HRMS_ENVIRONMENT=local`, CORS list, `HRMS_DOCUMENT_STORAGE=local` | 600 |
| `frontend/.env` | local | `VITE_API_URL` = `https://hrmsapi.alvision.in` — **intentional**: the Vite dev server also serves `testinghrms.alvision.in` through the tunnel, so browsers need the public API address. For private local-only work use `http://localhost:8015`. | 664 |
| `deploy/aws/testing.runtime.env` | testing | RDS URLs for `hrms_app`/`hrms_platform`, secret key, metrics token, encryption keys, CORS, S3 bucket, pool sizes, timezone, `HRMS_MAIL_BACKEND=disabled` | 600 ✅ |
| `deploy/aws/testing.migrate.env` | testing | RDS **owner** URL, app + platform role passwords | 600 ✅ |
| `deploy/aws/testing.deploy.env` | testing | public compose settings: web API URL, ports 8115/8180, bind address, memory | 600 ✅ |
| `deploy/env/testing.env` | testing (older self-hosted-Postgres route) | owner/app/platform passwords, secret key, metrics token, encryption keys, S3, backup settings | 600 |
| `deploy/env/production.env` | production | same shape, with placeholder hostnames | 600 |
| `ops/.env` | monitoring | `GRAFANA_ADMIN_PASSWORD` | 600 |
| `ops/secrets/testing-metrics-token`, `ops/secrets/production-metrics-token` | monitoring | the `/metrics` bearer token for each environment | 644 (must stay readable: Prometheus runs as user `nobody`) |
| `ops/alertmanager/alertmanager.yml` | monitoring | alert e-mail/Slack target + SMTP login (template: `alertmanager.yml.example`) | — |
| `.env` (repo root) | legacy | **Old Node stack** (port 5440, `DATA_KEY`, `JWT_SECRET`). The current FastAPI app does **not** read it. | 600 |
| `credential.md` | reference | plain-text logins for the source ERP systems (Suraj Group, RABS India) ⚠️ | 600 ✅ |
| `backups/` (e.g. `try-login.txt`) | local | scratch backups/notes; whole folder git-ignored | dir 700 ✅ |
| `exim.*.json`, `Sharanga_Production.*.json` | history migration | raw ERP exports with real user/login records ⚠️ | 600 ✅ |
| `backend/storage/` | local | uploaded documents (encrypted), plus `maintenance-backups/`, `migration-backups/` | — |

**Tracked templates (safe, no real secrets):** `backend/.env.example`, `frontend/.env.example`,
`deploy/env/*.env.example`, `deploy/aws/*.env.example`. `backend/.env.example` contains the
*published* development key and passwords — usable on `local` only.

---

## 5. Every secret explained

| Variable | What it is for | Used in | If lost or leaked |
|---|---|---|---|
| `HRMS_DATABASE_URL` | Owner DB login for migrations/scripts (also fallback) | all | full database control |
| `HRMS_APP_DATABASE_URL` | `hrms_app` login the API runs as | all | tenant data access |
| `HRMS_PLATFORM_DATABASE_URL` | `hrms_platform` login for the platform console | all | platform takeover |
| `HRMS_APP_ROLE_PASSWORD` / `HRMS_PLATFORM_ROLE_PASSWORD` | Passwords the migration sets on those two logins; must match the URLs | testing, prod | app can't connect if they differ |
| `RDS_OWNER_PASSWORD` | RDS owner password (GitHub secret → `testing.migrate.env`) | testing | full database control |
| `HRMS_DB_OWNER_PASSWORD` | Owner password for the self-hosted Postgres container | `deploy/env/*` | — |
| `HRMS_SECRET_KEY` | Signs login tokens (JWT, ≥ 32 chars) | all | anyone can forge a login; changing it logs everyone out |
| `HRMS_METRICS_TOKEN` | Required to read `/metrics` | testing, prod | metrics exposure |
| `HRMS_FIELD_ENCRYPTION_KEYS` | `<id>:<32-byte key>`; first = active. Encrypts Aadhaar, PAN, bank account and uploaded documents | all | **lose it = data unreadable forever** (RDS backups do not include it) |
| `GRAFANA_ADMIN_PASSWORD` | Grafana `admin` login | `ops/.env` | dashboard access |
| `HRMS_PLATFORM_ADMIN_PASSWORD` | Initial platform-admin password for `seed_platform_admin.py` (script input, not stored) | scripts | — |
| `HRMS_INITIAL_PASSWORD`, `HRMS_DEMO_PASSWORD` | Passwords used by seed/import scripts (never run `seed_demo` on testing) | scripts | — |
| `HRMS_SENTRY_DSN`, `HRMS_WEB_SENTRY_DSN`, `VITE_SENTRY_DSN` | Error tracking (Sentry); **unset = off** | optional | — |
| `RELEASE_PLEASE_TOKEN` | Optional GitHub token for release PRs (falls back to `GITHUB_TOKEN`) | GitHub | — |
| SMTP password in `alertmanager.yml` | Sends alert e-mail | monitoring | — |

---

## 6. Other settings you will see

Not secret. Full list with defaults: `backend/src/hrms/core/config.py`.

- **Identity of the deployment:** `HRMS_ENVIRONMENT` (local/testing/production), `HRMS_VERSION`, `HRMS_ENV_FILE`
- **Network:** `HRMS_CORS_ORIGINS`, `HRMS_WEB_API_URL`, `HRMS_API_PORT`, `HRMS_WEB_PORT`, `HRMS_BIND_ADDRESS`, `HRMS_FORWARDED_ALLOW_IPS` (172.30.25.1 = Docker bridge gateway)
- **Documents:** `HRMS_DOCUMENT_STORAGE` (`local`|`s3`), `HRMS_DOCUMENT_S3_BUCKET`, `HRMS_DOCUMENT_S3_REGION`, `HRMS_STORAGE_DIR`
- **Behaviour:** `HRMS_ALLOW_PUBLIC_REGISTRATION` (false on testing), `HRMS_API_DOCS_ENABLED` (true on testing, false on production), `HRMS_DEFAULT_TIMEZONE` (Asia/Kolkata), `HRMS_JOBS_DAILY_AT` (00:30), `HRMS_THROTTLE_ENABLED`, login lockout limits
- **Performance:** `HRMS_DATABASE_POOL_SIZE`/`_MAX_OVERFLOW` (5/5 on testing), `WEB_CONCURRENCY` (2), `HRMS_API_MEMORY` (1g)
- **Logging:** `HRMS_LOG_LEVEL`, `HRMS_LOG_FORMAT` (json when deployed)
- **Mail:** `HRMS_MAIL_BACKEND` = `disabled` (SES supported; needs `HRMS_MAIL_FROM`, `HRMS_PLATFORM_RESET_BASE_URL`)
- **Backups:** `HRMS_BACKUP_DIR`, `HRMS_BACKUP_AT` (01:30), `HRMS_BACKUP_KEEP_DAYS` (14), `HRMS_BACKUP_REMOTE` (encrypted rclone off-site destination)
- **Tests/tools:** `HRMS_TEST_DATABASE_URL`, `HRMS_QUERY_METRICS`, `PERF_PERSONAS`, `RUSH_CONCURRENCY`
- **Frontend:** `VITE_API_URL`, `VITE_SENTRY_DSN`, `VITE_SENTRY_ENVIRONMENT`; deployed web reads `/config.js` (see below)

**How the web app learns its API address.** Locally, `frontend/.env` → `VITE_API_URL`
(fallback `http://localhost:8015`). When deployed, the web container runs
`deploy/web/40-hrms-config.sh` at start-up, writes `/config.js` from `HRMS_WEB_API_URL`,
and builds the security policy from it (`frontend/src/lib/runtimeConfig.ts` reads it). One image
is promoted from testing to production unchanged.

---

## 7. What lives outside this machine

| Where | What is stored | Who manages it |
|---|---|---|
| **GitHub → Settings → Environments → `testing` → Secrets** | `RDS_OWNER_PASSWORD`, `HRMS_APP_ROLE_PASSWORD`, `HRMS_PLATFORM_ROLE_PASSWORD`, `HRMS_SECRET_KEY`, `HRMS_METRICS_TOKEN`, `HRMS_FIELD_ENCRYPTION_KEYS` | you. If any is missing, the workflow warns and keeps the files already on EC2. |
| **Same environment → Variables** (public) | `AWS_REGION`, `AWS_ACCOUNT_ID`, `AWS_ROLE_ARN`, `AWS_TESTING_ENABLED`, `EC2_INSTANCE_ID`, `DEPLOY_ARTIFACT_BUCKET`, `ECR_API_REPOSITORY`, `ECR_WEB_REPOSITORY`, `EC2_IMAGE_PLATFORM`, `RDS_HOSTNAME`, `RDS_DATABASE`, `RDS_OWNER_USERNAME`, `HRMS_WEB_API_URL`, `HRMS_CORS_ORIGINS`, `HRMS_DEFAULT_TIMEZONE`, `HRMS_DOCUMENT_STORAGE`, `HRMS_DOCUMENT_S3_BUCKET`; optional `FRONTEND_ECS_ENABLED` | you |
| **EC2 `/etc/hrms/`** | the 3 env files (root, mode 600) and `rds-global-bundle.pem` (RDS CA certificate) | `deploy.sh` installs them |
| **EC2 `/opt/hrms/testing/releases/…`** | each release bundle; symlink `current` = live release; `deploy.lock` prevents parallel deploys | `deploy.sh` |
| **S3 artifact bucket** `testing/releases/<sha>/…tar.gz` | the deployment bundle **including env files with real secrets** | CI |
| **AWS RDS** | database `hrms_testing` and its three logins | AWS / migration |
| **S3 `hrms-testing-docs`** | uploaded documents; also `testing/seed/` for history-migration input files | EC2 instance role |
| **ECR** | `hrms-testing-api`, `hrms-testing-web` images | CI |
| **AWS IAM** | GitHub OIDC deploy role; EC2 instance profile (SSM/ECR/S3) | CloudFormation `deploy/aws/bootstrap.yml` |
| **Cloudflare** | DNS + tunnel for the two testing hostnames | you |
| **GHCR** `ghcr.io/novusha-lpp/hrms/{api,web}` | release images for the `deploy/compose.yml` route | `release.yml` |
| **Source ERPs** (Suraj Group "EXIM", RABS/Sharanga) | the history being migrated; logins in `credential.md`, raw dumps in `exim.*.json` | their owners |

---

## 8. CI, releases, monitoring and backups

| Workflow / tool | What it does | Secrets it uses |
|---|---|---|
| `checks.yml` | tests on every change | none |
| `commits.yml` | commit-message check | `GITHUB_TOKEN` (automatic) |
| `deploy-testing-ec2.yml` | deploy `testing` branch to EC2 | the 6 testing secrets + variables above |
| `release.yml` | release-please PRs, builds versioned images to GHCR, optional frontend ECS deploy | `RELEASE_PLEASE_TOKEN` (optional), `GITHUB_TOKEN` |
| `ops/docker-compose.monitoring.yml` | Prometheus, Grafana, Alertmanager, blackbox, node-exporter | `ops/.env`, `ops/secrets/*` |
| `deploy/backup/*.sh` | nightly Postgres dump + documents into `HRMS_BACKUP_DIR`; `copy-offsite.sh` syncs to `HRMS_BACKUP_REMOTE` (encrypted rclone) | rclone remote credentials (not in repo) |

Backups: RDS has its own automated backups. The **encryption keys are not in any backup** —
keep them in a password manager.

---

## 9. Problems found — status

**Fixed on 2026-10-21**

| Problem | What was done |
|---|---|
| Real RDS passwords readable by every user (mode 644) | `deploy/aws/testing.{runtime,migrate,deploy}.env` → 600 |
| `credential.md`, `.env`, `backend/.env`, ERP dumps (`exim.*.json`, `Sharanga_Production.*.json`) group/world-readable | → 600; `backups/` → 700 |
| Prometheus probed only the tunnel hostnames, not the AWS site | `ops/prometheus/prometheus.yml` now also probes `testhrms…`/`testhrmsapi…` (labelled `deployment: aws`) — **restart Prometheus to apply**: `docker restart hrms-prometheus` |
| `ENVIRONMENTS.md` listed only one testing URL pair | updated to explain both pairs |
| Doc said `frontend/.env` was a mistake | corrected: it is intentional (the tunnel serves the Vite dev server to remote browsers); changing it to localhost would break `testinghrms.alvision.in` |

**Deliberately left as is**

- `ops/secrets/*-metrics-token` stay mode 644: the Prometheus container runs as `nobody` and could not read a 600 file.

**Needs you (I did not do these — they are deletions or live in other systems)**

1. **Back up `HRMS_FIELD_ENCRYPTION_KEYS`** in your password manager. RDS backups do not contain it; losing it loses Aadhaar/PAN/bank data and every uploaded document.
2. **Move the ERP logins out of `credential.md`** into a password manager, then delete the file.
3. **S3 deployment bundles contain all testing secrets.** In AWS, confirm the artifact bucket is private, encrypted and expires old releases.
4. **Delete the raw ERP dumps** (`exim.*.json`, `Sharanga_Production.*.json`) once the history migration is signed off.
5. **Delete the legacy root `.env`** if the old Node stack is gone.
6. **Decide the production route**: `deploy/compose.yml` + `deploy/env/*` (self-hosted Postgres) or `deploy/aws/` (RDS). Testing on AWS uses the second.
7. **Production isn't deployed**, so `deploy/env/production.env` still holds placeholder hostnames.

*Not checked:* whether any secret value is reused between local and testing (values were not compared).

---

## 10. How-to: change or rotate things

| I want to… | Do this |
|---|---|
| Change a **testing** secret | Update it in GitHub → Environments → testing → Secrets, then push/redeploy the `testing` branch. CI rewrites `/etc/hrms/testing.*.env`; migration re-sets the DB role passwords. Editing on EC2 directly: `sudoedit`, keep root + mode 600. |
| Rotate the **encryption key** | Put the new key **first**, keep the old after it (`new,old`), deploy; migration re-encrypts. Remove the old key only after that finishes. |
| Rotate `HRMS_SECRET_KEY` | Change it and redeploy. Everyone must sign in again. |
| Change a **local** setting | Edit `backend/.env` / `frontend/.env`, restart uvicorn / Vite. |
| Rotate the **metrics token** | Change `HRMS_METRICS_TOKEN` in GitHub and the matching `ops/secrets/<env>-metrics-token`. |
| Change **Grafana's** password | Edit `ops/.env`, then `grafana cli admin reset-admin-password` (the env var only applies on first creation). |
| Set up **production** | Copy `deploy/env/production.env.example` → `deploy/env/production.env`, fill every secret (`openssl rand -hex 32`), replace example hostnames, generate a fresh encryption key (`python3 -c "import os,base64;print('k1:'+base64.urlsafe_b64encode(os.urandom(32)).decode())"`), store it in the password manager. |
| Turn on **error tracking** | Set `HRMS_SENTRY_DSN` (API) and `HRMS_WEB_SENTRY_DSN` (web) — see OBSERVABILITY.md. |
| Turn on **e-mail** | `HRMS_MAIL_BACKEND=ses`, plus `HRMS_MAIL_FROM` and an https `HRMS_PLATFORM_RESET_BASE_URL`. |

---

## 11. Glossary

- **RDS** — Amazon's managed PostgreSQL. **EC2** — the virtual server. **ECR/GHCR** — where Docker images are stored (AWS / GitHub).
- **SSM** — AWS Systems Manager; lets CI run the deploy script on EC2 without SSH.
- **OIDC** — GitHub proves its identity to AWS directly, so no AWS keys are stored.
- **Instance role** — AWS permissions attached to the EC2 server itself (used for S3).
- **RLS (row-level security)** — Postgres rule that stops one company seeing another's rows.
- **JWT** — the signed token proving a user is logged in. **Tenant** — one customer company.
- **Metrics token** — password for the `/metrics` page that Prometheus reads.
- **Bundle** — the tarball (compose file, scripts, env files, image list) CI sends to EC2.

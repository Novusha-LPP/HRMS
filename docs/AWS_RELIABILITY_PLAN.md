# HRMS: AWS hosting with self-hosted monitoring

Status: design and acceptance plan only. No AWS resources, networking, monitoring targets,
credentials, live database or tunnel changes are implemented by this plan.
The application fixes are described in [RELIABILITY_FIXES.md](RELIABILITY_FIXES.md).

## Decision and target

Use AWS for application hosting, PostgreSQL, document storage, secret custody and email.
Run Grafana, Prometheus, Alertmanager and blackbox exporter yourself on a separate monitoring
host. Do not put monitoring on the application workstation or rely on Grafana dashboards
alone for incident detection.

A realistic 9/10 requires measured recovery and failure handling, not merely AWS service names.
Proposed acceptance targets, to be agreed before purchasing capacity:

- Availability: 99.9% successful critical workflows, measured over at least 30 days.
- Recovery point: at most 15 minutes of accepted changes lost in a recovery incident.
- Recovery time: at most 60 minutes to restore usable login, punch, approval and KYC access.
- Ordinary API requests: p95 below 500 ms under the agreed concurrent workload, measured
  separately from exports, bulk accrual and cold reports. Cold reports have a separate
  30-second construction deadline; the load test must establish a usable lower p95 target.
- No duplicate accrual, cross-tenant reads or inaccessible committed KYC document references
  after failover or restore. If these targets fail in a drill, the system is below the gate.

These are proposed objectives, not guarantees or evidence of current production performance.

## Proposed topology

| Component | Production design | Project-specific work still required |
| --- | --- | --- |
| Web/API | Two EC2 hosts in different availability zones, same immutable image digests, managed by an Auto Scaling Group behind HTTPS ALB | Adapt current loopback-only compose bindings and local-db dependencies; readiness, rolling drain and trusted proxy/IP verification |
| Background jobs | Separate jobs process/host using the existing PostgreSQL advisory lease and persistent tenant checkpoints | Verify scheduler restart/catch-up, duplicate-start rejection and alerting; document historical accrual baseline |
| PostgreSQL | Private RDS PostgreSQL 16 Multi-AZ instance deployment, encrypted storage, automated backups/PITR | Validate migrations 0001–0042 on RDS and the restricted hrms_app role; migration owner has a distinct credential |
| KYC documents | Private S3 bucket with versioning, encryption and least-privilege instance roles | Existing HRMS_DOCUMENT_STORAGE=s3 adapter is available; migrate existing encrypted objects and prove DB/object consistency |
| Secrets | AWS Secrets Manager for signing, DB, metrics, mail and historical field encryption keys; KMS protects AWS secret/storage encryption | Bootstrap protected runtime files or explicit provider integration; current code reads environment variables, not Secrets Manager directly |
| Mail | SES with verified sender, production sending access and delivery monitoring | Existing encrypted reset outbox remains disabled until real delivery/retry is verified |
| Monitoring | Dedicated self-hosted EC2 monitoring host, preferably a separate AWS account; Grafana/Prometheus/Alertmanager/blackbox on private interfaces | Adapt ops/docker-compose.monitoring.yml to scrape remote hosts; populate production targets and configure a real receiver |
| Independent checks | Public hostname probes and monitoring heartbeat outside the application account/provider | Must detect application-host, tunnel, monitoring-host and regional failures even when Prometheus cannot send |
| Recovery | Cross-account backup destination and independently accessible key custody; documented replacement environment | Demonstrate restore without the workstation or its filesystem |

EC2 is the initial recommendation because this repository already ships Docker Compose and
host backup tooling. ECS can be a later alternative, but converting deployment models during
this recovery project adds work. One EC2 app host is an interim deployment and retains an app
host failure point. Two containers on that one host do not satisfy the production topology.

Do not use the existing hand-started workstation cloudflared process as the only production
entry point. Prefer ALB ingress with DNS/TLS and restricted origins. If Cloudflare Tunnel is
retained, run supervised connectors on both application hosts, validate failover, and keep
metrics/docs behind access controls. Cookie-authenticated web/API hosts must share a site,
use HTTPS and exact CORS origins. Re-test forwarded client IPs through the actual proxy chain;
copying the present Docker bridge gateway trust into an ALB topology would be incorrect.

## 1. Freeze inputs and protect recovery material — Critical

Owner: operator supplies account, region, domain, retention and budget; engineering prepares
reviewable deployment changes later. Default region candidate: ap-south-1 for the current
Asia/Kolkata workload, subject to actual user location and recovery requirements.

Inventory tenant count, largest tenant, peak punch concurrency, current PostgreSQL bytes,
KYC object count/bytes, daily growth, exact image digests and current active/historical keys.
Record identities and incident owners. Separate testing and production accounts where practical;
at minimum use separate VPCs, databases, buckets, keys and IAM roles. Synthetic load data only
belongs in isolated testing. No live HR/KYC data in CI artifacts or developer worktrees.

Take and restore a current database/document backup before changing hosting. Store key copies
outside this workstation and outside the sole production administrator account. Keep a manifest
of object checksums, key IDs and database backup coordinates, never raw keys in Git or logs.
**Acceptance:** another authorized operator can recover and decrypt a protected test restore
using only independently held material.

## 2. Prepare RDS and test compatibility — Critical

Use private database subnets in two availability zones, no public access, security groups
allowing PostgreSQL only from app/jobs/migration roles, TLS certificate and hostname verification
with the AWS CA bundle. Test the actual asyncpg SSL configuration; merely adding sslmode=require
is insufficient certificate verification. Require deletion protection and controlled maintenance.
Set an explicit storage growth ceiling, alarms and backup retention (initial proposal: 35 days).

The current migration suite assumes PostgreSQL owner privileges and creates/configures hrms_app.
RDS does not grant ordinary PostgreSQL superuser access. Rehearse every migration and role grant
in isolated RDS; fix unsupported privilege assumptions before moving production. Preserve
NOSUPERUSER/NOBYPASSRLS for runtime credentials. Never switch the API to the RDS master user
as a workaround. Validate row-level security and encrypted MFA seed migrations too.

Count connections across processes, not containers. Current defaults are pool_size=5,
max_overflow=5 and two API workers: up to 20 API connections per host. Two hosts allow up to
40, before scheduler lease/work, migrations, exports, monitoring and administrative reserve.
Report construction opens a second session while holding the authenticated request session.
Load-test this pool interaction; bound concurrency before adding replicas or workers. Add RDS
Proxy only after validating SQL session state, tenant SET LOCAL and advisory locks on the exact
configuration; a proxy is not a substitute for a connection budget.

Multi-AZ protects availability through a synchronous standby in another zone; its standby does
not serve report reads. Measure added commit latency and connection recovery during forced
failover. PITR creates a new instance, so the runbook must include the new endpoint, credentials,
TLS and app restart, with performance warm-up. [AWS Multi-AZ documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZSingleStandby.html),
[AWS PITR documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIT.html).

**Acceptance:** populated upgrades and all RLS/security tests pass on RDS; a staging failover
recovers workflows without manual data repair or duplicate jobs. LatestRestorableTime lag is
monitored and a restore meets the agreed RPO/RTO.

## 3. Move documents and retain keys — Critical

Enable S3 versioning and Block Public Access, private IAM instance roles, TLS-only access and
server-side encryption. Application field/document AES-GCM encryption remains necessary.
KMS storage encryption does not replace HRMS_FIELD_ENCRYPTION_KEYS or its ciphertext format.
Use environment-specific buckets and role permissions; no shared production/testing bucket.
Choose noncurrent-version retention longer than the database restore window plus a recovery
margin, then estimate its storage cost. [S3 versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html).

Before cutover, quiesce document writes, upload encrypted objects without changing their storage
keys, verify sizes/checksums, switch storage mode and decrypt representative KYC previews.
Database PITR and object versions are independent. Current metadata does not record S3 version
IDs. Establish a timestamp/version manifest or add that metadata in a future reviewed change
so a database restored to T can recover each referenced object as of T. Test deletion and
replacement, not just uploads. Leave no committed document row pointing to an unavailable blob.
S3 versioning within the same account is insufficient protection from privileged deletion;
plan cross-account backup/replication and independent restore permissions.

Store the complete ordered field-key set in Secrets Manager; the first key is active. The current
code loads a key set at process startup. Stage a new secret version, retain old keys, roll out,
run encrypt-pii/rekey including MFA seeds, verify, then retire old keys only after all retained
backups and object versions that need them expire. Do not enable generic automatic random
rotation of field keys: it does not rewrite the application's ciphertext. Signing-key rotation
invalidates existing sessions and needs a deliberate user-visible rollout. DB password rotation
must refresh process pools and job connections. [Secrets Manager rotation](https://docs.aws.amazon.com/secretsmanager/latest/userguide/rotating-secrets.html).

**Acceptance:** restore a deleted historical document and a matching database point; decrypt KYC
and enrolled MFA with recovered historical keys. Denied S3/Secrets access fails clearly and alerts.

## 4. Build self-hosted monitoring — High

Deploy Prometheus, Grafana, Alertmanager and blackbox exporter on a dedicated monitoring host,
with persistent disks and backed-up configuration/Grafana state. Pin supported, patched versions
and image digests when implementation starts; the repository currently pins Prometheus 2.51.0,
Grafana 10.4.0 and Alertmanager 0.27.0, so do a current upgrade/compatibility review before reuse.
This plan does not upgrade or deploy those images.

Keep service interfaces private. Grafana may use a TLS access proxy with SSO/MFA; disable anonymous
access/signup and constrain admin access. Prometheus, exporters and Alertmanager must not be
public. Operators should reach them through a VPN or approved private access path. Metrics may
expose infrastructure or business information. [Prometheus security model](https://prometheus.io/docs/operating/security/),
[Grafana security configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/).

The existing monitoring compose uses host networking and localhost listeners. A remote Prometheus
cannot scrape an app host's 127.0.0.1 endpoint. In the later implementation, create private routable
scrape endpoints with narrow security groups and authenticated/TLS access. Retain the API metrics
bearer token and protected secret files. Do not publish exporters through the public tunnel.

Scrape/probe:

- Each API replica: /metrics with its token and /health/ready; public UI/API HTTPS separately.
- Each app/jobs host: node exporter, disk/memory, container/process availability and restart rates.
- Scheduler success/checkpoint age and failures; encrypted email outbox lag and failed deliveries.
- RDS: CPU, free storage, connections, failovers and latest restorable time via CloudWatch read-only
  exporter/API integration. SQL exporter, if needed, gets a separate restricted monitoring role;
  it must not receive migration credentials or unrestricted tenant data access.
- Backup freshness and actual restore-drill outcome, S3 errors, decryption errors and KMS/Secrets
  failures. Existing metrics/rules need a gap review rather than assuming they cover all of these.
- Prometheus scrape failures, disk usage, rule evaluation errors, Alertmanager notifications and
  a dead-man heartbeat consumed by a service outside this monitoring host/account.

Initial scrape interval: 30 seconds; readiness probes: 60 seconds. Initial retention: 15 days
and an explicit disk cap, adjusted from measured series volume. Avoid person IDs, emails or
request IDs as Prometheus labels. Control cardinality before adding per-tenant labels.
Use one Alertmanager routing policy with severity, environment and runbook links. The operator
chooses email/Slack/Telegram and confirms receipt; a configured receiver without a delivery test
is incomplete. Do not rely exclusively on the same SES path that is being monitored.

Start with one monitoring host plus an independent uptime/heartbeat service. It remains a
monitoring availability risk: document detection/rebuild time and inject a host outage. If that
gap violates response objectives, add a second Prometheus/Alertmanager in another zone/account
and deduplicated notifications. Self-hosting transfers patching, disk and recovery work to us;
it does not inherently reduce operational risk.

**Acceptance:** stop an API replica, block RDS, fail a backup, break SES and stop monitoring in
isolated testing. Every actionable failure reaches the designated owner within five minutes;
resolved notifications and runbook instructions work. No public /docs or unauthenticated /metrics.

## 5. Rehearse migration and same-image promotion — High

1. Build/release verified images from the reviewed code; check the Release sync-lockfiles job,
   release token and GHCR digests. Do not deploy moving tags or edit a running checkout.
2. In isolated AWS testing, migrate through 0042 and run browser/security tests with HTTPS,
   actual proxy headers, secure cookies, MFA and the production CORS topology.
3. Exercise 10,000 employees across multiple tenants, peak punch bursts, approvals, month-end
   accrual, report generation/paging/export and simultaneous scheduler runs. Record API/RDS
   p95/p99, pool waits, CPU/memory, storage growth and snapshot cleanup costs.
4. Rehearse import and document transfer. Verify counts, ledger invariants, tenant access,
   pending outbox handling and KYC decryption. Handle imported never-changed passwords only
   in the approved cutover database; complete the account-by-account privilege review.
5. Freeze writes for the final transfer, measure downtime, migrate, validate and switch ingress.
   Keep the old deployment read-only for a defined rollback window. After new writes are
   accepted, switching back to the old database would lose/diverge data; use a tested forward
   recovery or reconciliation procedure instead.
6. Promote the identical image digests from testing to production. Confirm enrollment, email
   delivery, alerts, backups, TLS, denied cross-origin writes and no browser-stored credentials.

## 6. Recovery proof, operations and costs — Critical

Perform one full independent restore before go-live, monthly initially, then quarterly after
stable evidence. The drill restores PostgreSQL at a chosen point, matching document versions,
historical keys, image digests, runtime IAM/secrets and DNS/ingress. Validate login/MFA, a punch,
a leave approval, ledger balances, KYC previews and tenant isolation; measure recovery from the
incident decision, not just from the database becoming available. Simulate a production account
or monitoring-host loss. Record operator, timestamps, checks and failures in the incident runbook.

Review regional disaster recovery separately. Same-region Multi-AZ is not regional recovery.
Decide whether cross-region backups and a rebuild plan meet the chosen RTO; rehearse instead of
claiming a 60-minute regional recovery from configuration alone.

Use AWS Pricing Calculator for the selected region and measured capacity before implementation.
Budget separately for two app hosts, RDS Multi-AZ, RDS backups beyond allowances, S3 versions/
replication, recovery drills, monitoring EBS, load balancer, NAT/endpoints, cross-zone/region
traffic, CloudWatch API calls, Secrets/KMS, SES and external probes. Choose private endpoints
versus NAT from traffic and cost estimates. AWS Budgets alerts do not hard-cap spending. Set
storage autoscaling maximums, report retention and metric cardinality limits; review costs monthly.

## Completion and score gate

Engineering can prepare application changes and, later, deployment IaC/runbooks. The operator
must choose budget/account/region, supply protected credentials, approve live cutover and name
an incident owner/receiver. Infrastructure work starts only when authorized separately.

The project reaches the proposed 9/10 gate only when CI and production-like tests are green,
RDS failover works, independent full recovery meets RPO/RTO, notifications survive monitoring
outage, peak/month-end load meets budgets, production/testing are separated, and at least 30 days
of workflow availability evidence support the rating. Current local tests and this plan do not
establish those operational facts.

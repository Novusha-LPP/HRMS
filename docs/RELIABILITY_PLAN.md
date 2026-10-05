# Combined reliability implementation and acceptance plan

The live checkout is /home/aiserver/HRMS. The previous hardening changes and follow-up
source fixes are now on main. The user explicitly authorized direct edits and a backed-up
live schema upgrade through 0042. Changes remain uncommitted. Production releases should
still use verified immutable images rather than editing a running checkout.
No 9/10 claim is valid until the operational acceptance gates below have evidence.
The chosen AWS/self-hosted monitoring design is [AWS_RELIABILITY_PLAN.md](AWS_RELIABILITY_PLAN.md);
it is plan-only. Current application work is documented in [RELIABILITY_FIXES.md](RELIABILITY_FIXES.md).

## Gate A: safe release

- Complete migrations 0034–0038 and reconcile their metadata using additive migrations 0039–0040.
- Green lint, mypy, Alembic consistency, populated upgrades, all backend tests, frontend tests/build.
- Backup failure injection: dump, validation, archive and lock failure never publish success.
- Old platform sessions rejected after credential changes; reset links consumed under a row lock.
- Scheduled database failures contained in an outer savepoint; departed caller rejected immediately.
- Release lockfile checkout uses actual release-please output, not a guessed branch.
- Publication explicitly depends on the complete reusable checks workflow.

## Gate B: deployed testing with real recovery (operator configuration required)

1. Preserve the current database, document volume and current keys. Verify a pre-cutover restore.
2. Fill in the deployed env file. Store encryption keys outside this host, with historical keys retained.
3. Configure encrypted off-site backup storage and alert receiver. Never mirror retention deletions.
4. Start release images on 8180/8115, migrate and verify readiness, restricted docs/metrics and documents.
5. Switch only the HRMS entries in config3.yml. Identify the exact tunnel process before restarting it.
6. Verify separate client IPs and rejected spoofed forwarded headers with the configured bridge gateway.
7. Stop only the HRMS development processes. Preserve the old database for the agreed rollback window.
8. Review imported never-changed accounts; set forced-change flags on the NEW database after approval.
9. Enable Prometheus scrapes/readiness/backup exporter and actual Alertmanager delivery. Simulate failures.
10. Restore the full application on another host: database, document references, decryption and login.

Initial targets: RPO <=15 minutes, RTO <=60 minutes. Nightly dumps do not satisfy this RPO;
continuous PostgreSQL recovery must be configured before accepting that target.
Local backup locks document row changes while taking pg_dump + file snapshots; budget this write pause.
S3 deployments require versioned object recovery, not the local-volume archive alone.

## Gate C: dependable workflows

- Job lease prevents duplicate schedulers; per-tenant checkpoints catch missing periods.
- Historical policy/eligibility semantics must be reviewed before choosing a backfill baseline.
- Each tenant's IANA timezone is stored in tenants.timezone (India is the initial default).
- SES sender/account verified and delivery tested before enabling password recovery emails.
- Browser workflows: login, punch, leave application/approval, correction, KYC and session failures.
- Bounded account/daily-analysis responses, request deadlines, isolated storage I/O and query budgets.
- Access review by actual responsibilities. No arbitrary two-admin cap; managers get justified scopes.

## Gate D: independent infrastructure and proof of 9/10

- Separate testing and production hosts/accounts. Same verified image digests promoted between them.
- Managed PostgreSQL or dedicated VM with PITR, monitored storage, backups and tested failover.
- Versioned/private S3 documents and key access through Secrets Manager/KMS or equivalent provider.
- Privileged MFA/session architecture validated; CSP tested with API and optional error tracking.
- Multi-tenant 10,000-employee benchmark and month-end writes against the real deployment topology.
- Monthly restore drills initially; incident owner, escalation channel and capacity/cost budget assigned.
- 30 days meeting explicit availability, latency, recovery and data-loss objectives.

No real employee test database, raw credentials or personal exports belong in worktrees or CI.
Provider/account, backup destination, SES sender, alert receiver and live cutover decisions remain
operator inputs; do not invent them or silently provision billable resources.

## Implementation status (isolated worktree)

| Original step | Delivered code / evidence | Remaining acceptance |
| --- | --- | --- |
| 1 | Uncommitted follow-up applied directly to main by request; private backup and live additive upgrade through 0042 approved | Deploy immutable images; retire HRMS reload processes during cutover |
| 2 | 0034–0038 carried forward; 0039 metadata/checkpoints; 0040 encrypted mail outbox | PR CI and review; do not downgrade across irreversible boundaries |
| 3 | Actual release-please branch checkout; publication depends on all checks | RELEASE_PLEASE_TOKEN configured; merge release; verify GHCR images |
| 4 | Strict deployed-environment validation and env examples | Provide protected secrets and independent encryption-key custody |
| 5–7 | Throwaway compose smoke, private backup restore, restricted runtime DB role | Pre-cutover real backup/restore, approved cutover/tunnel/password enforcement |
| 8 | Failure-safe backup, document snapshot lock with bounded duration, checksums, append-only off-site copy, metrics and restore script | Encrypted remote, scheduled host jobs, full restore on independent host |
| 9 | Narrow forwarded-IP trust and separate bridge gateways | Verify real tunnel client IPs and spoof rejection after cutover |
| 10 | Readiness probes, node exporter, 19 validated rules, opt-in production monitoring | Real alert receiver and external checks; test receipt with injected failures |
| 11 | Connection-held advisory lock; persistent per-tenant periods; retries; timezone-based month | Approve historical backfill semantics/baseline; monitor successful runs |
| 12 | Existing privilege/scoping guards retained | Account-by-account access review; no arbitrary administrator cap |
| 13 | Existing tenant admin reset; SES reset outbox with encrypted payload, retries and expiry cleanup | Verified SES sender/IAM and real delivery; keep disabled until configured |
| 14–15 | Provider-neutral acceptance requirements | Host/account/budget decision, PITR, independent secrets custody and versioned document storage |
| 16 | CI browser tests: login, punch, leave apply/approve, correction, image preview, transient session failure | CI execution and additional cross-browser coverage where required |
| 17 | Restrictive CSP, platform tokens shortened, credential epoch revocation | HttpOnly browser cookies and encrypted authenticator enrollment delivered in the follow-up; verify real HTTPS topology and privileged rollout |
| 18–19 | Same-image promotion model and explicit RPO/RTO and incident acceptance gates | Separate production infrastructure, incident ownership and measured recovery drills |
| 20 | Account filtering/pagination in SQL; bounded persisted daily snapshots and single-pass CSV in follow-up | Verify concurrent production load, snapshot retention and pool budgets |

Router splitting means internal modules/services, not a demand for distributed microservices.
A refactor alone does not improve availability; prioritize measured query and recovery failures.

## Known limits: do not count these as solved

- The live installation has not been changed by this branch and gains none of these safeguards until cutover.
- Default accrual recovery starts in the current tenant month. Earlier periods need an explicitly reviewed
  baseline because historical policy versions/rehire semantics may change what should be credited.
- Follow-up daily analysis computes once in batches of 250 and persists scoped/user-owned snapshots.
  Paging/export reuse those rows. The 10,000-employee local sequential check passed; concurrent
  production load, report write amplification and database pool saturation still require evidence.
- Account UI can still collect multiple pages. SQL pagination limits each request; it is not a claim that
  the browser can comfortably display arbitrarily large directories.
- SES delivery is at least once, with single-use reset tokens. A worker crash after sending and before
  commit can send a duplicate message on retry. No plaintext reset URL is stored or logged.
- Field/document keys must outlive retained backups. Pending mail ciphertext expires quickly; retain
  the prior active key until pending reset deliveries expire or are processed during key rotation.
- Nightly backup/restore smoke proves basic database recovery, not 15-minute RPO or 60-minute RTO.
- Local monitoring on the application workstation cannot detect its own total outage. Independent
  monitoring and actual notification delivery are mandatory before the 9/10 acceptance gate.
- Frontend production dependency audit is clean. Five high-severity development dependency advisories
  remain in Tailwind 3's glob stack; the available fix requires a Tailwind 4 migration. Do not run
  untrusted glob input in the build environment; do not hide these findings with blanket audit ignores.

## Deployment/recovery sequence

1. Review and merge the verified branch; validate the release workflow and immutable image digests.
2. Allocate isolated testing/production infrastructure and an off-site recovery destination.
3. Record the signing secret, active/historical encryption keys and DB credentials in independent custody.
4. Back up the current real DB and documents; restore/decrypt them in an isolated protected environment.
5. Populate testing.env, configure SES (optional until verified), encrypted remote and alert receiver.
6. Follow docs/ENVIRONMENTS.md to start/migrate the testing release on 8180/8115. Verify all smoke checks.
7. Verify proxy/client-IP behavior, then switch the two tunnel routes and perform acceptance workflows.
8. Review and enforce imported-account password changes, validate tenant access grants and register owners.
9. Install one-minute backup metric export and daily off-site copy/age checks. Configure remote retention
   separately (at least the agreed recovery window); append-only copy intentionally does not delete remote data.
10. Enable PITR and restore the full stack to the recovery host. Measure RPO/RTO, document missing objects
    and actually decrypt KYC samples with recovered keys. Test alert delivery and failover.
11. Run representative multi-tenant/month-end load tests on that topology; fix budget violations.
12. Promote the same image digests to production and collect availability/recovery evidence before rating 9/10.

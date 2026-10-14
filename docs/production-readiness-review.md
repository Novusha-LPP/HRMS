# Production readiness review — 14 October 2026

Reviewed on `codex/fix-0064-tenant-key`, isolated from the live main checkout.

## Resolved code blockers

- Migration 0064 identifies duplicate grants by `(tenant_id, id)`. A PostgreSQL regression test preserves a same-ID grant in another tenant.
- Profile, KYC and leave edit forms capture the version when editing starts; background query refreshes no longer substitute a newer version into an old edit.
- Backend typechecking passes after correcting domain-map, metric-family and SQLModel select types.
- Punch carry-over tests now mock the service dependency and distinguish expired day sessions from current overnight sessions.
- Holiday import normalization is tested with synthetic source data; CI no longer requires the ignored real-company export.
- Deployment encryption verification runs in the maintenance container rather than the restricted jobs container.
- Global email preflight counts explicitly filter by tenant even when the connection bypasses RLS.

## Verified evidence

- Backend lint and typechecking: pass.
- Full backend suite: 3,189 passed, 4 skipped; coverage 91.18% against the required 88% (454 seconds). The run emitted 994 warnings; passing checks do not imply a warning-free application.
- Migration replay, populated upgrade, reversible rollback and protected rollback boundary: pass. Alembic reports no new upgrade operations (no detected schema drift).
- Frontend production build: pass. Frontend unit tests: 10 pass in the current environment.
- Real-data preflight: 170 aggregate checks, zero violations, enforced read-only transaction using the configured restricted application login. No employee records or credentials printed or changed.
- Disposable deployment smoke: pass; includes health, hidden docs, metrics authentication, CORS, runtime password replacement, encryption checks, timeouts, jobs, web configuration and private backup/restore (89 tables).
- Synthetic encrypted recovery: database dump restored; identifier and document decrypted successfully. Small synthetic recovery time is not evidence of production RTO.

## Deployment gates still requiring operational evidence

- Publish and merge this corrective branch and obtain passing hosted CI on that exact commit.
- Promote the same tested image to testing before production.
- Confirm the production environment's distinct secrets, encryption-key custody and off-site backup access.
- Run a protected restore/decryption drill on the actual production backup volume and measure RPO/RTO. Nightly dumps do not meet the documented 15-minute RPO; PITR requires hosting configuration.
- No production deployment or live migration was performed by this review.

Hosted CI could not be verified from this session because the configured GitHub CLI authentication is invalid. These results cover the local corrective branch and disposable rehearsals, not a production deployment approval.

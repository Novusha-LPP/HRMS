# Reliability fixes and deployment acceptance

Changes are now applied directly to main in /home/aiserver/HRMS, uncommitted as requested.
The temporary branch was removed. Existing main edits were preserved, including a clean
three-way merge of the employee email/role additions in people/router.py.
The original checks below were performed in isolation; the approved main rollout is recorded
at the end of this document. AWS infrastructure remains plan-only.

## Code delivered

- Malformed encrypted fields/documents use FieldCryptoError, including truncated headers.
- Browser credentials use separate host-only HttpOnly cookies. Deployed cookies use the __Host- prefix and are Secure,
  SameSite=Lax. UI/API must share a site (for example hrms.example.com/api.example.com).
  Credentialed writes require the X-HRMS-Session header and an explicitly allowed Origin.
  Bearer API clients remain supported; browser login bodies contain no usable token.
- Tenant sessions last 60 minutes; platform sessions 30 minutes. Logout revokes all existing
  sessions for that account. Existing browser tokens are removed from localStorage on load;
  users must sign in again after this release. No silent token migration is attempted.
  Previously issued API bearer tokens retain their original expiry until revoked; privileged
  MFA enforcement rejects those without factor proof. Deliberate all-account epoch revocation
  at cutover is an operator decision if immediate invalidation of every old token is required.
- Authenticator enrollment requires the current password plus proof of the new factor.
  Seeds are encrypted. Codes use 30-second RFC 6238 steps, ±1 step clock tolerance,
  atomic replay prevention and rate limiting. Enrollment revokes existing sessions.
  Existing factors remain required even when the rollout flag is disabled. Password reset
  does not remove MFA. Privileged roles are SUPER_ADMIN, HR_MANAGER, ACCOUNTANT and all
  platform administrators. Keep host clocks synchronized.
- Daily analysis is built in batches of 250 with one repeatable-read source transaction.
  Scoped/user-owned snapshots expire in five minutes and retain at most two per user.
  The daily job also removes expired snapshots from users who never return.
  Paging and CSV reuse stored rows and recheck current scope. CSV uses one server-side
  pass with formula neutralization; refresh starts a new calculation. Responses expose
  capture time. Default report capacity is 25,000 employees; benchmark before increasing it.
- The test harness pins maintenance, readiness and import-script connections to the explicitly
  selected *_test database before application imports, preventing fallback to a shared database.
- No blanket mypy module exclusions remain. SQL expressions use SQLModel column types.

## Migration and rollout

1. Back up and independently restore the current database, documents and historical keys.
2. Run the isolated tests and CI, release immutable images, then upgrade through 0042.
   Authenticator seeds survive code rollback; do not downgrade away enrollment columns.
   Roll back only to an MFA-aware release, or disable privileged access during recovery:
   older auth code would ignore the enrolled factor even with the columns preserved.
3. Confirm the UI/API share a site and use HTTPS, exact CORS origins, cookie attributes,
   no token in browser storage/login JSON, and rejected cross-origin writes.
4. Set HRMS_PRIVILEGED_MFA_REQUIRED=true. Existing privileged users receive setup-only
   sessions until enrollment. Test a designated administrator first in isolated testing.
   Verify existing factors, wrong codes, replay rejection, password changes and logout.
5. Lost authenticator recovery is an operator procedure (not executed by this change): verify identity independently,
   record approval and an audit event, clear the account's seeds/counter and increment
   token_epoch in one transaction. Password-reset email alone must not authorize this.
6. AWS hosting, database, storage, secrets and monitoring are plan-only, per your instruction.
   Follow docs/AWS_RELIABILITY_PLAN.md when you authorize that work. No infrastructure
   overlay, target configurator or acceptance script is shipped in this change.

## Remaining operator work

External DB/backup accounts, PITR configuration, versioned private bucket, independent key
custody, production monitoring host/receiver, recovery host and enrollment are real
operational inputs. These are not marked complete by committing code or passing unit tests.
Use a separate production host/account and promote the same tested image digest.

## Implementation references

Authenticator algorithm: https://www.rfc-editor.org/rfc/rfc6238
Browser write protection: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html

## Measured performance (isolated local database)

The synthetic benchmark used 10,000 employees, 395,519 attendance days and 791,038 punches:
initial report 1.452 s; five cached pages 8–13 ms; CSV 0.143 s, 10,001 rows including header.
Calculation used 41 calls, never more than 250 employees per batch; process peak RSS 135.1 MiB.
This is a single-process in-process ASGI benchmark against private local PostgreSQL 16,
not concurrent AWS capacity evidence. Cold one-employee request budget is 20 SQL statements;
cached paging budget is 5. Initial construction adds persistence writes to avoid repeating
attendance/policy work on every page or export. Real topology concurrency/pool saturation,
report storage growth, and failover remain acceptance requirements in the AWS plan.

## Final local verification — 2026-10-05

- Fresh isolated PostgreSQL 16 database: 2,959 backend tests passed, four expected skips;
  coverage 90.69% (required minimum 88%). All test and maintenance connections pinned
  to that database. Backend ruff passed; mypy passed for all 111 source files.
- Frontend: 25 unit tests and three Playwright browser workflows passed. The browser
  build compiles TypeScript and produces the production bundle. Lint has no errors;
  existing frontend warnings remain.
- Browser checks include punch, leave approval, correction, decrypted KYC preview,
  transient /me failure and authenticator enrollment/login with session revocation.
- Populated migration upgrade through 0042, Alembic consistency and protected rollback
  boundaries passed. Schema downgrade refuses to erase authenticator enrollment.
- Freshly built release images passed the throwaway Compose smoke: readiness, hidden
  docs, authenticated metrics, CORS, DB role password/timeouts, encryption audit, jobs,
  web security/config and private backup restored into a 64-table temporary database.
- The temporary Compose stack was removed and the private synthetic PostgreSQL cluster
  stopped after verification. No AWS services were provisioned. These are local results;
  CI and the actual AWS topology still require their own acceptance evidence.

## Approved main integration — 2026-10-05 10:35 IST

- User authorized direct source changes on main and then explicitly approved a private
  backup plus additive live migrations before installing the runtime files.
- Pre-migration database archive: /home/aiserver/HRMS/backend/storage/maintenance-backups/20261005T050337Z/before-0041-0042.dump.
  Mode 0600 in a mode-0700 directory. SHA-256 and size are in the adjacent backup.json.
  pg_restore could read its catalog; this is archive validation, not a full restore drill.
- Live schema upgraded 0040 -> 0042; Alembic reported no missing schema operations.
  No PII rekey, forced password updates, MFA enablement or AWS provisioning was performed.
- Combined source plus existing employee changes: 66 targeted backend regressions passed;
  backend ruff and mypy passed; 25 frontend unit tests and the production build passed.
- The initial full-suite and browser results above apply to the isolated fixes. Main
  preserves additional concurrent edits, which need their own review and CI checks.

- After installing the main files, the live /health/ready returned 200 with both database
  and schema checks OK. The new MFA/logout/export routes appeared in OpenAPI, and an
  untrusted-origin browser write was rejected with 403 before any authenticated mutation.
- Final checks on main: backend lint and mypy passed (111 source files), frontend test
  files/build passed, and three dashboard regressions passed on the private synthetic DB.
  Concurrent dashboard work needed explicit list types and SQL line wrapping; its query
  behavior and the other existing employee/organization edits were preserved.
- All changes remain unstaged/uncommitted on main. The pre-migration archive remains local;
  independent off-site recovery, AWS deployment and the 9/10 evidence gates are still pending.

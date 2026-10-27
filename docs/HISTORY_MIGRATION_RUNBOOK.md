# Running the history migration on the testing server

Brings the old EXIM and Sharanga history (punches, leave, regularizations, RABS people,
documents and photos) into the hosted RDS database. Every step is repeatable: running a
script again adds nothing. The data files contain personal data and are never committed;
they travel as a private bundle and are deleted afterwards.

## Before you start
1. The code with migration `0066` (attendance status override) is deployed to `testing`.
   Check on RDS: `select version_num from alembic_version;` shows `0066`.
2. Take an RDS snapshot (`before-history`) and wait until it is **Available**.
3. Confirm RDS still holds the starting data (nobody added anything since the first load):
   `punches` 773, `attendance_days` 452, `leave_applications` 23, `persons` 268
   (plus the two demo tenants' rows until they are purged).

## 1. Get the bundle onto the instance
Upload `history-bundle.tar.gz` (built from this repo's `backups/aws-bundle/`) in the S3 console to
`hrms-testing-docs/testing/seed/`. In CloudShell (your own login) print the ready-to-paste
download command, copy it **without pasting it anywhere else**, and run it on the instance:

```bash
echo "curl -fsS -o /tmp/history-bundle.tar.gz \"$(aws s3 presign s3://hrms-testing-docs/testing/seed/history-bundle.tar.gz --expires-in 900 --region ap-south-1)\"; echo \"curl exit code: \$?\""
```

On the instance, check and unpack, then delete the S3 object straight away:

```bash
sha256sum /tmp/history-bundle.tar.gz        # must equal the checksum recorded when it was built
mkdir -p /tmp/hist/reports && tar -xzf /tmp/history-bundle.tar.gz -C /tmp/hist
```

## 2. Run the import (dry run first)
```bash
IMG=$(sudo docker inspect hrms-testing-aws-api-1 --format '{{.Config.Image}}')
run() { sudo docker run --rm --network host \
  --env-file /etc/hrms/testing.runtime.env --env-file /etc/hrms/testing.migrate.env \
  -e HRMS_ENVIRONMENT=testing -e HRMS_DEBUG=false -e PGSSLROOTCERT=/app/rds-ca.pem \
  -e REPORT_DIR=/seed/reports \
  -v /etc/hrms/rds-global-bundle.pem:/app/rds-ca.pem:ro -v /tmp/hist:/seed \
  -w /seed/backend "$IMG" "$@"; }
run bash scripts/run_history.sh /seed/rabs_decisions.json            # dry run: reports only
run bash scripts/run_history.sh /seed/rabs_decisions.json --apply    # the real run
```

## 3. Check the result
`punches` 34,223 · `attendance_days` 19,462 · `leave_applications` 1,173 ·
`leave_balance_transactions` 1,923 · `attendance_correction_requests` 1,096 ·
`persons` 275 · `user_accounts` 281. Running step 2 with `--apply` again must change none of them.

## 4. Documents and photos (encrypted with the server's own keys)
```bash
run python scripts/migrate_employee_documents.py --tenant suraj-group --source exim --report /seed/reports/docs-suraj.json            # dry run
run python scripts/migrate_employee_documents.py --tenant suraj-group --source exim --apply --report /seed/reports/docs-suraj.json
run python scripts/migrate_employee_documents.py --tenant rabs-industries-india-private-limited --source sharanga --apply --report /seed/reports/docs-rabs.json
run python scripts/migrate_employee_documents.py --tenant rabs-industries-india-private-limited --source exim-rabs --decisions /seed/rabs_decisions.json --apply --report /seed/reports/docs-rabs-exim.json
```
Each report lists files that are gone from the old bucket or unsupported (`follow_up`), by employee
code and field, for HR to ask for again.

## 5. Remove the two demo tenants
```bash
run python scripts/purge_tenant.py --slug bernhard-and-sons          # dry run
run python scripts/purge_tenant.py --slug park-conley-llc            # dry run
run python scripts/purge_tenant.py --slug bernhard-and-sons --yes
run python scripts/purge_tenant.py --slug park-conley-llc --yes
```

## 6. Clean up
Delete the S3 object, `/tmp/hist` and `/tmp/history-bundle.tar.gz` on the instance, and the local
`backups/aws-bundle`, `backups/aws-delta` and `backups/rabs-review.csv`. Keep the `before-history`
snapshot for a few days.

---

# Reload from the 2026-10-26 export

A newer export replaced the 19 October one (punches to 26 Oct, 3 new Suraj people, all leave to date).
Rehearsed on a private copy of the dev database; every number below came from that run. It is
**not yet run on RDS**.

What the reload does: empties the attendance, leave and import-audit data (`scripts/wipe_activity.sql`),
adds the 3 new Suraj people, then runs the same ordered history import. It keeps tenants, legal entities,
people, accounts, passwords, roles, policies, calendars, documents, KYC, regularization requests and the
platform admins.

## Not covered
- **Regularization requests (1,096 on dev)** have no file in this export, so they are kept, not rebuilt.
  `run_history.sh` skips those steps when `exim.regularizationrequests.json` is absent.
- **Drivers** (56 accounts, 5,429 day rows, 100 quotas, 4 requests) are not imported: the accounts have no
  name, company or mobile, only a username.
- `pulse_do` ("DO Team Pulse", company "novusha") is a shared team login and is left out on purpose.
- 89 RABS punches stay unlinked: they belong to the one held person (Manoj Kumar Arth).

## Steps (on the instance, same `run` helper as above, bundle unpacked to /tmp/hist)
1. RDS snapshot `before-reload`, wait for **Available**.
2. Bundle `history-bundle-2026-10-26.tar.gz`, sha256 `f2aedc09988a9848273581403d81d9e6a9cca5fe729d13602921fc8a835464b0`.
3. **Save the punches made in HRMS** (microsecond timestamps, plus the ERP/CRM integration ones) — the wipe deletes
   them and the export cannot replace them. Add `--skip-integration` to leave the integration punches out:
   `run python scripts/preserve_live_punches.py export --file /seed/live-punches.json`
   Keep a copy outside the instance too: it holds real punch data.
4. Wipe: run `scripts/wipe_activity.sql` through the same database connection (see the ad hoc `python -c` command in the chat).
5. New people: `run python scripts/migrate_tenants.py --tenant suraj --suraj-tenant suraj-group --data-dir /seed --allow-partial --yes`
6. `run bash scripts/run_history.sh /seed/rabs_decisions.json` (dry run), then again with `--apply`.
7. Put the saved punches back (dry run first, then `--apply`); days where they clash with imported punches are marked
   `MISSED_PUNCH` + `LEGACY_CONFLICT` for HR to resolve, the same as the import does:
   `run python scripts/preserve_live_punches.py restore --file /seed/live-punches.json [--apply]`
8. Expect: `punches` 35,048 · `attendance_days` 19,943 · `leave_applications` 1,188 ·
   `leave_balance_transactions` 1,759 · `persons` 278 (RDS may differ if people were added in the app).
   Running step 5 with `--apply` again must change none of them.
9. Delete `/tmp/hist`, the tarball and the S3 object; keep the snapshot a few days.

---

# Teams (reporting lines) from `exim.teams.json`

Separate step, run after the history reload. Rehearsed on a copy of the dev DB: 85 Suraj and 32 RABS lines
created, a second run created none, no loops, nobody with two managers. Not yet run on RDS.

What it does: every member of an **active** team gets the team's HOD as their LINE manager
(`scripts/migrate_exim_teams.py`). It only fills gaps: an existing line is never changed. A person in two
active teams keeps the first team in the file. Skipped and reported: members who are inactive or unlinked,
the HOD themselves, teams whose HOD is inactive in the old system (HR Admin / Deepak Singh: 10 people;
Test features: 2), loops. No org units are created, because HRMS has no team membership.

```bash
run python scripts/migrate_exim_teams.py --tenant suraj-group                                   # dry run
run python scripts/migrate_exim_teams.py --tenant suraj-group --apply
run python scripts/migrate_exim_teams.py --tenant rabs-industries-india-private-limited --company rabs --decisions /seed/rabs_decisions.json --apply
```
Expect 85 and 32 lines created on a database like the dev copy; RDS can differ if lines were entered in the app.
Running a step again must say `same line already set` and create nothing. Per-team detail is written to
`/tmp/hrms-team-lines.json` inside the container; pass `--report /seed/reports/teams-suraj.json` to keep it.

---

# Repair documents and photos that cannot be opened (`--repair`)

Found 2026-10-26: the 571 documents loaded on 19 Oct were encrypted on the developer's machine with key id
`k1`, which the testing server does not have, so `FieldCryptoError: document was encrypted with key 'k1': not
configured` and every profile picture falls back to initials. Only documents saved on the server open.
`migrate_employee_documents.py --repair` downloads each unreadable document again from its old address and
saves it under the same reference with the server's own key. The database rows stay. Rehearsed on a copy that
had exactly this problem: 466 Suraj + 104 RABS repaired, a second run repaired nothing, every document opened.
Files gone from the old bucket (153 Suraj, 1 RABS) stay unreadable and are listed for HR.

Run on the instance with the bundle unpacked to /tmp/hist (reports folder `chmod 777`), same `run` helper:
```bash
run python scripts/migrate_employee_documents.py --tenant suraj-group --source exim --repair --report /seed/reports/d1.json
run python scripts/migrate_employee_documents.py --tenant suraj-group --source exim --repair --apply --report /seed/reports/d1.json
run python scripts/migrate_employee_documents.py --tenant rabs-industries-india-private-limited --source sharanga --repair --apply --report /seed/reports/d2.json
run python scripts/migrate_employee_documents.py --tenant rabs-industries-india-private-limited --source exim-rabs --decisions /seed/rabs_decisions.json --repair --apply --report /seed/reports/d3.json
```
Check afterwards that every document opens (script in the chat); a documents key is never copied to the server.

---

# Identity and bank numbers show "[unreadable: encryption key not available]"

Found 2026-10-26 on an employee's profile (PAN, Aadhaar, passport, account number). The protected values
(`employee_kyc_records`: pan, aadhaar, uan, pf, esi, passport, licence, voter id, account number) were saved
under key id `k1`, which the server no longer has, so they cannot be shown. The same cause as the unreadable
documents above. `migrate_tenants.py` now replaces a protected value that cannot be decrypted with the source
value, encrypted under the active key; anything readable (including what HR has entered since) is left alone,
and the run reports `kyc_values_re_encrypted`. Rehearsed on a copy with the same fault: 450 values repaired,
a second run repaired none, 215 compared values equal the source. Needs `exim.users.json` and the Sharanga files
(in the bundle). Values that exist only in the app (not in the old systems) and are unreadable cannot be
recovered this way: HR has to enter them again.
```bash
run python scripts/migrate_tenants.py --tenant suraj --suraj-tenant suraj-group --data-dir /seed --allow-partial --dry-run
run python scripts/migrate_tenants.py --tenant suraj --suraj-tenant suraj-group --data-dir /seed --allow-partial --yes
run python scripts/migrate_tenants.py --tenant rabs --rabs-tenant rabs-industries-india-private-limited --data-dir /seed --allow-partial --yes
```

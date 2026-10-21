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

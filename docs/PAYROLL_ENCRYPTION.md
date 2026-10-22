# Payroll encryption (keys, pepper, salt)

Salaries are encrypted in the database with keys that are **separate from every other secret**, so a
developer or DBA who can read the database, a backup, or the identifier keys sees no salary.

## What is protected

| Where | What | How |
|---|---|---|
| `employee_compensations.annual_ctc` | each employee's CTC | AES-256-GCM, stored as `pay:v1:<key id>:<token>` (migration 0073) |
| `entity_change_log.changes` for `employee_compensation` | old/new CTC in the audit trail | same sealing (`seal_amount`) |

Not encrypted: salary-structure templates (component percentages/limits) and statutory rates. They are
company-wide settings, not a person's pay, and payroll needs to read them in SQL.

## How the three ingredients work

- **Key** (`HRMS_PAYROLL_ENCRYPTION_KEYS`): `<id>:<base64url 32 bytes>`, first = active. Not the same as
  `HRMS_FIELD_ENCRYPTION_KEYS`; deployed environments refuse a reused key.
- **Pepper** (`HRMS_PAYROLL_PEPPER`, 32+ random characters): never stored in the database or next to the key.
  The AES key is `HKDF-SHA256(key, salt = pepper, info = purpose | key id | column)`, so the key alone and
  the pepper alone both decrypt nothing, and each column has its own derived key.
- **Salt**: every value gets its own random 96-bit nonce, so two people on the same CTC have different
  stored values and a value cannot be matched, grouped or replayed from the database.

(A hash-style salt+pepper cannot be used for pay itself, because payroll has to read the amount back.
That construction is for passwords, which are already hashed separately.)

## Operating it

```bash
python -m hrms.deploy encrypt-payroll [--check]   # every deploy runs it; idempotent
python -m hrms.deploy decrypt-payroll             # only to downgrade migration 0073
```

- Generate: keys `python3 -c "import os,base64;print('p1:'+base64.urlsafe_b64encode(os.urandom(32)).decode())"`,
  pepper `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`.
- Rotate keys: put the new key **first**, keep the old after it, deploy. Remove the old one only when
  `encrypt-payroll --check` reports 0. The pepper cannot be changed by a deploy alone.
- **Losing the key or the pepper loses every salary.** Keep both with the backups' owner, offline.
- Local development uses published dev keys (never accepted outside `local`).

## Several keys, several peppers, and a lost key

- **Keys:** `HRMS_PAYROLL_ENCRYPTION_KEYS=p2:<new>,p1:<old>`. First is active; the rest only read.
- **Peppers:** `HRMS_PAYROLL_PEPPER` is either one pepper (used for every key) or one per key:
  `p2:<new pepper>,p1:<old pepper>`. A retired key keeps the pepper it was written with, so
  you can rotate both without decrypting anything first. Every key id must have a pepper.
- **If an old key (or its pepper) is gone:** the deploy no longer stops. It rewrites what it can
  open, lists what it cannot as a `::warning::` (ids only), and carries on. In the app, that
  salary shows an error ("Salary unreadable: …key 'p1', which is not configured") in the salary
  list, the single-employee salary returns `409 ENCRYPTION_KEY_UNAVAILABLE`, and an unreadable
  identifier shows `[unreadable: encryption key not available]` and cannot be saved over.
  Everything under the new key works normally. Adding the old key and pepper back makes the old
  data readable again; nothing is deleted or overwritten.
- `python -m hrms.deploy encrypt-payroll --check` (and `encrypt-pii --check`) still exit 1 while
  unreadable values exist, so you can see what is left.

## Limits to be honest about

- Anyone who can run the application with production secrets, read its environment, or hold both the key
  and the pepper can decrypt. To keep developers out, give them **no access to the production/testing
  secret store, server shell or CI secrets**, and have only the payroll owner set these two values.
- Salaries are still shown (decrypted) to payroll-permitted users through the API, by design.
- The database can no longer filter, sort or total salaries; payroll does that in Python.

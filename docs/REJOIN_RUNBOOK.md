# Leavers, rejoining and moving between companies: runbook

For whoever runs the environment and for HR administrators. Design and history of the work:
[REJOIN_PLAN.md](REJOIN_PLAN.md) (scenarios and research) and
[REJOIN_DEVELOPMENT_PLAN.md](REJOIN_DEVELOPMENT_PLAN.md) (build programme and progress log).

## 1. What it does

| Situation | What the system does |
|---|---|
| Someone leaves | The stint of their employment closes. If the company has a leave rule for leavers, unused leave is lapsed, paid out (up to a cap) or held. With no rule nothing happens, as before |
| Someone rejoins | One employment record continues (a new stint opens). HR chooses **Continue** (earlier service and held leave carry on) or **Start fresh** (unused leave lapses, service for leave starts again). The company's rejoin policy sets the default and the longest break that may continue |
| Someone who has worked here is added again | The Add employee screen warns on a matching name (and birth date); the API refuses a second employment for the same person unless confirmed |
| Someone moves to another company of the group | Their job ends in the first company and a new one starts in the second the same day. Leave is carried over or settled; login, identity details and documents follow them |
| Someone worked elsewhere before | Earlier service is recorded and can count towards leave eligibility and gratuity |

Nothing here is switched on by a flag. A company with **no leave rule and no rejoin policy** behaves
exactly as before: leave is untouched when someone leaves, and a rejoin continues earlier service.

## 2. Setting it up for a company

1. **Leave policies → Leavers & Rejoining.**
2. Under *Unused leave when someone leaves* add a rule: company and leave type (or *every*), what
   happens (lapse, pay out, hold), the start date. The rule applies to separations from that date.
   A rule starting today does not apply to someone whose last day was last month.
3. Under *When someone rejoins* add a policy: default (continue or start fresh), the longest
   break that may continue, the start date.
4. Check the help (the *How this works* button) with HR before going live. The wording of legal
   points is deliberately cautious; confirm gratuity and leave-on-exit rules with your labour adviser.

## 3. Day to day

| What | Where |
|---|---|
| Held leave lapses or is restored | The daily `leave-holds` job (`python -m hrms.jobs run leave-holds` to run it by hand). Safe to run any number of times |
| Reports | Leave policies → Leavers & Rejoining → Reports (people who rejoined, leave settled for leavers, moves between companies), as a table or CSV. Names that a spreadsheet could read as a formula are prefixed with an apostrophe |
| Who changed a rule or policy | `entity_change_log` entity types `leave_separation_rule`, `rejoin_policy`, `prior_service`, `company_transfer` (written by database triggers) |
| Metrics | Grafana *HRMS Employment Lifecycle* (`/d/hrms-lifecycle`); see [OBSERVABILITY.md](OBSERVABILITY.md) |

### Integrity checks (nightly job, alert above zero)

| Check | Means | What to do |
|---|---|---|
| `employment_without_current_stint` | An employment has no record of the stint it is in | Should be 0 after migration 0067. Find them with the first query below and report it: a writer bypassed `people/spells.py` |
| `employment_with_two_open_stints` | More than one stint with no end date | Same |
| `employment_without_service_start` | `continuity_start_date` is empty | Set it to the hire date |
| `held_leave_overdue` | Held leave past its hold date by more than 2 days | The `leave-holds` job is not running: check the jobs container |

```sql
-- employments without their current stint
SELECT e.id, e.employee_number FROM employments e
WHERE e.archived_at IS NULL AND NOT EXISTS (
  SELECT 1 FROM employment_spells s
  WHERE s.tenant_id = e.tenant_id AND s.employment_id = e.id AND s.spell_no = e.current_spell_no);

-- held leave still waiting
SELECT count(*), min(hold_expires_on) FROM leave_separation_settlements
WHERE action = 'HOLD' AND resolution IS NULL;
```

## 4. Common questions

- **"I added someone who had worked here before."** The new record has none of their history.
  Use *Rehire* on the old record next time. If the duplicate already exists, ask the developer: the
  two employments belong to one person and can be reconciled; do not delete either.
- **"A rejoin needs a reason."** Start fresh always does; continuing after a break longer than the
  company limit needs the break accepted and a reason; gratuity paid at exit forces Start fresh.
- **"The leave didn't lapse when they left."** Check there was a rule in force on the last working
  day (rules apply from their start date), that the leave type is not unlimited, and that the person
  had a balance on that day (the *Reports → Leave settled for leavers* list shows what happened).
- **"Transfer is refused."** A change is already scheduled for the person (cancel it), the date is in
  the future (transfers take effect today or earlier), they have left (rehire instead), or you
  don't manage both companies.

## 5. Permissions

| Action | Needs |
|---|---|
| See or change leave rules for leavers | `leave.read` to list, `leave.write` to add or remove |
| Preview what a separation does; see an employee's settlements; the settlements report | `leave.read` over the employee |
| See or change rejoin policies | `people.read` to list, `people.write` to add or remove |
| Rejoin preview, employment history, a person's earlier service, the rejoin and move reports, a person's employments | `people.write` over the employee |
| Move a person to another company | `people.write` over **both** companies |
| Record or remove earlier service | `people.write` over any employment of the person |

Reports and lists show only people the caller's access covers. Another tenant's data is never
visible: every new table has row-level security, tested in `tests/test_lifecycle_security.py`.

## 6. Rollout

1. Deploy. Migrations `0067`–`0072` only **add** tables and columns, so the release that is still
   running keeps working while they apply. They backfill one stint per existing employment.
2. After the deploy run the checks in section 3. All four integrity checks must read 0.
3. Open Leave policies → Leavers & Rejoining for one company, add the rules, and try a rejoin on a
   test person with the preview before using it for real.
4. Watch the lifecycle dashboard for a week.

**Rehearse first** on a copy, never on the live database:

```bash
HRMS_DATABASE_URL=postgresql+asyncpg://…/hrms_rehearsal python scripts/rehearse_lifecycle_rollout.py
```

It builds a database at migration 0066 with synthetic people and leave, upgrades it, proves nothing
changed and every employment got one stint, proves the downgrade refuses while lifecycle entries
exist in the leave ledger and works once they are gone, and upgrades again without duplicating
anything. It refuses a database not named `*_rehearsal` or `*_test` or one that has tables.

## 7. Rolling back

- **To the previous release:** just deploy it. The schema only grew, so it runs on the new tables
  unchanged (proved by running the previous release's whole test suite against the new schema).
- **Removing the settings:** archive the rules and policies in the screens. Nothing already settled
  is changed.
- **A wrong settlement or rejoin:** correct it with a leave adjustment (*Grants & Operations*).
  Entries are never deleted, so the history stays honest.
- **Downgrading migrations** (`alembic downgrade 0066`) is for a scratch copy. On a real database it
  refuses while lifecycle entries (`SEPARATION`, `REJOIN`, `TRANSFER` references) are in the leave
  ledger, because the ledger is history. Take a backup first.

## 8. Performance (private database, 10,000 people)

| Measure | Result |
|---|---|
| Leavers and rejoiners reports, 5,000 rows (the cap) | 41–107 ms, 3 SQL statements (no per-row queries) |
| Daily `leave-holds` job, 10,000 held balances | 23 s (2.3 ms each), one transaction per company |
| Monthly accrual, 10,000 active people who all have earlier service | 1.0 s |
| Upgrade to head with 600 employments | 0.8 s |

Reproduce with `perf/lifecycle_load.py --employees 10000` (see `perf/README.md`). After a bulk
load run `ANALYZE`: a table with no statistics gets a poor plan until autovacuum has run (the
first measurement of the settlements report was 2.6 s for this reason).

## 9. Not built (decisions for later)

- **Approval of a rejoin or move** by someone other than the person recording it: `people.write` is
  the approval today, as for every other personnel action.
- **Notifications** to HR or payroll: there is no notification module; connected apps are told
  through events (`employee.rehired` carries `rejoin_mode`; a move produces `employee.separated` and
  `employee.hired`).
- **Future-dated moves between companies**: enter the move on the day.
- **Full and final settlement payroll and gratuity amounts.**
- **Legal verification**: the rules are company choices recorded with their reasons. Nothing in the
  product states legal advice.

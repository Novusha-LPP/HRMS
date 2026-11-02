# Scheduled mails (birthdays, anniversaries, joiners, exits and late arrivals)

In the app this is **Scheduled mails** (menu: Settings). The code, tables and API keep the earlier
name *reminders*.

HR sets up rules that email people ahead of a birthday, work anniversary, joining date or last
working day. Everything about a rule is data: which event, for which company or department, how often, at what time, who is told
and the wording. Nothing needs a deploy to change.

## Switched on per company (platform)

Not every company needs this, so it is an optional **service** the platform switches on per
company. A platform admin opens the company in the platform console and ticks **Services →
Scheduled mails** (`PATCH /v1/platform/tenants/{id}` with `{"services": ["SCHEDULED_MAIL"]}`,
recorded in the platform audit log as `TENANT_SERVICES_CHANGED`; viewers cannot change it).
`tenants.enabled_services` (migration 0079) holds the list; a company starts with none.

While it is off: the menu item is hidden, `/v1/reminders/*` answers `403 SERVICE_NOT_ENABLED`,
the job queues nothing and sends nothing (mail already queued waits and goes out when it is
switched back on, unless it is older than two days). Rules and history are kept. The company's
own `/me` response lists its services (`services`), which the client uses to hide the menu item.

## How a rule works

- **Event**: `BIRTHDAY` (from `persons.date_of_birth`), `WORK_ANNIVERSARY` (from
  `employments.continuity_start_date`, else `hire_date`), `NEW_JOINER` (from `hire_date`) or
  `EXIT` (from `separation_date`). Birthdays and anniversaries repeat every year; joiner and exit
  are one-off dates. Someone who joined this year has no anniversary yet. People who have left
  are not included, except by an `EXIT` rule (which looks at people who have not yet left, last
  day included). A 29 February event is observed on 28 February in years without one. Placement
  (department, manager, job title) is read as of the later of today and the joining date, so a
  joiner who has not started still shows theirs.
- **When**: a list of "days before the event" (0 is the day itself). The presets fill it in:
  `SAME_DAY` {0}, `ONE_DAY_BEFORE` {1}, `CONTINUOUS` {N..0}, `ALTERNATE_DAYS` every second day
  counting back from N plus the day itself, `CUSTOM` the days HR typed. `send_time` is the time
  of day in the tenant's timezone.
- **Who**: the person (a greeting, **sent on the day itself only**, however early the schedule
  starts), their line manager (a heads-up for their reports), everyone (`notify_everyone`: every
  employee with an email in the rule's company and department, told about everyone but
  themselves) and extra addresses (a heads-up for everyone the rule covers). `digest` sends one
  mail listing everyone due; otherwise one mail per person.
- **Scope**: a company, and optionally a department, which also covers the departments beneath it.
- **Wording**: a subject and an HTML body for the heads-up mail, and another pair for the
  person's own mail. Use `{variable}` (`GET /v1/reminders/variables`). A heads-up listing several
  people repeats the part between `{#each}` and `{/each}` once per person. Unknown variables are
  refused on save, so a mail never goes out with a literal `{placeholder}`. The body is cut down
  to a safe set of tags on save and every value is HTML-escaped when filled in.

## Late arrivals (a daily report)

`LATE_ARRIVAL` looks at what already happened rather than ahead to a date. Each day at `send_time`
it lists the people who arrived late **that day**, read from `attendance_days.late_by_minutes`,
which the attendance policy computes (grace period included), so there is one definition of
"late". `min_late_minutes` (1-600, default 1) hides small amounts.

- Scope is the same as any rule: the whole group, one company, or one department (and the ones
  beneath it).
- Who: the addresses typed on the rule (they get the full list for the scope), each person's line
  manager (only the late people in their own team) and, optionally, each late person (a short note).
  "Everyone" is not allowed. It is always one list per recipient on `SAME_DAY`.
- A day on which nobody is late sends nothing.
- Anyone who arrives after `send_time` is not in that day's mail, so set the time after people
  are expected in (the form suggests 11:00).
- "Who will get mail soon?" is empty for this event: who is late is only known on the day.

## How it runs

`python -m hrms.jobs schedule` runs the `reminders` job every 15 minutes (the other jobs run
daily). Each run, per tenant:

1. **tick**: for each active rule whose `send_time` has passed locally and that has not run today
   (`last_run_date`), work out who is due and queue one `reminder_outbox` row per mail. The unique
   key `(rule, dedupe_key)` makes a repeat harmless.
2. **deliver**: send queued mail in batches of 50, up to 1000 per run (the rest go out on the next run), (SES, `core/mail.send_html`), wording each one at that
   moment, so an edit to a rule applies to mail not yet sent. A failure is retried with a growing
   delay, five attempts in all. Mail for a rule that was paused or removed, or more than two days
   old, is marked FAILED instead of sent.
3. **purge**: delivered or failed rows are removed after 90 days.

A rule saved after its time of day has passed starts tomorrow, not at once. Nothing is queued or
sent while `HRMS_MAIL_BACKEND=disabled`.

## Mail transport

`HRMS_MAIL_BACKEND` is `disabled`, `ses` or `smtp`. SMTP (`core/mail._smtp_send`) needs
`HRMS_MAIL_FROM`, `HRMS_SMTP_HOST`, `HRMS_SMTP_USERNAME` and `HRMS_SMTP_PASSWORD`, and optionally
`HRMS_MAIL_FROM_NAME`, `HRMS_SMTP_PORT` (587) and `HRMS_SMTP_STARTTLS` (true). SMTP covers
scheduled mail only; password-reset mail still needs `ses`.

## API

`/v1/reminders` (see the API docs, tag **Reminders**): rules (list, create, get, change, remove,
history), `POST /preview` (a draft filled with sample people), `GET /rules/{id}/upcoming` (who and
on which dates), `POST /rules/{id}/test-send` (to yourself), `GET /deliveries`. Access is
`org.read` to see and `org.write` to change; a group-wide rule needs group-level `org.write`.

## Known limits

- The mail header shows the company name in its brand colour; the uploaded logo is not embedded
  (logos are stored encrypted and need an authenticated request, which mail clients cannot make).
- Mail goes out within about 15 minutes of `send_time`.
- The rich-text editor is a small built-in one (bold, italic, underline, list, link, fields).
- "Everyone" mails each employee separately. SES's sending rate limit applies; very large
  companies take more than one run to finish.
- Not built: a "department head" or "company HR" recipient, resignation (as opposed to last day)
  as a trigger, custom date fields.

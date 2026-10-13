"""Endpoint docs: Integrations (connected apps) and Integration settings."""

_KEY = """
**Authentication:** the app's API key in `X-API-Key`, or a token from
`POST /v1/integrations/oauth/token`. Needs the `{scope}` scope.
"""

_LOGGED = """
Every call, including a refused one, is written to the app's sync log (Settings → Integrations).
Quote the `request_id` from the response when reporting a problem.
"""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Credentials ─────────────────────────────────────────────────────────
    "oauth_token": (
        "Get an integration token (OAuth 2.0 client credentials)",
        """
For apps whose security policy requires OAuth instead of a static key header.

Send `grant_type=client_credentials` as a form, with the client credentials in HTTP Basic auth
(or as `client_id` and `client_secret` form fields):

- `client_id` is the key's public part, `hrms_<env>_<prefix>` (shown on the key in Settings).
- `client_secret` is the whole API key.

Returns a bearer token valid for 15 minutes, with the same scopes, IP limits and company limits as
the key. Send it as `Authorization: Bearer <token>` on `/v1/integrations/*`. Revoking the key ends
its tokens at once.

**Errors:** `401 invalid_client`; `400 unsupported_grant_type`; `429` after repeated failures
from one address.
""",
    ),
    # ─── Reference data ──────────────────────────────────────────────────────
    "reference_data": (
        "List the values HRMS accepts (companies, departments, locations, designations)",
        _KEY.format(scope="employees.read")
        + """
What your `company`, `department`, `location`, `designation` and `role` values are matched
against, plus the mappings already set for your app. HRMS matches a value by mapping first, then
by exact code, then by exact name (ignoring case).

A value that matches nothing is refused with `422 UNKNOWN_<KIND>` and appears in HR's *Unmapped
values* list. Once HR maps it, retry the same call.
""",
    ),
    # ─── Employee sync ───────────────────────────────────────────────────────
    "upsert_employee": (
        "Create or update an employee",
        _KEY.format(scope="employees.sync")
        + """
`external_id` is your system's ID for the employee. The first call creates the employee
(person, employment, placement, login and role, in one transaction) or links an existing HRMS
employee; later calls update them.

**Send only the fields that changed.** Fields you leave out stay as they are; an explicit
`null` clears an optional field. Fields your app doesn't own under the company's settings are
ignored with a `FIELD_OWNED_BY_HRMS` warning (or refused, if the settings say so).

**Creating** needs `first_name`, `last_name`, `company`, `department`, `designation`,
`hire_date` and `location` (unless the company has a default location). `employee_code` is
required unless the company has an employee ID scheme in HRMS, in which case HRMS issues the
code and returns it: store it.

**Linking instead of creating:** send `employment_id` to link an employee hired in HRMS. Without
it, HRMS links automatically when the code and name and date of birth (or email) match an
unlinked employee. A partial match is refused with `409 POSSIBLE_DUPLICATE` and queued for HR;
retry after HR confirms.

**Order:** send `source_updated_at` (when the record changed in your system). An update older
than one already applied is ignored (`STALE_IGNORED`), so a delayed retry can't undo a newer
change.

**Job changes** (department, location, designation, manager) become personnel actions dated
`effective_date` (default today), so HRMS keeps the history. `change_reason` is `TRANSFER`
(default), `PROMOTION`, or `CORRECTION` (fix the current placement without a history entry).

**Passwords** (needs `passwords.sync`): `password_hash` as a bcrypt hash, or `password` in plain
text over HTTPS. Without either, the company's default pattern applies.

`?dry_run=true` returns exactly what would change, and saves nothing.

**Outcomes:** `CREATED` (201), `LINKED`, `UPDATED`, `NO_CHANGE`, `STALE_IGNORED`.

**Errors:** `422 UNKNOWN_DEPARTMENT` (and the other kinds), `FIELD_REQUIRED`,
`ROLE_NOT_ALLOWED`, `UNSUPPORTED_PASSWORD_HASH`, `COMPANY_CHANGE_NOT_SUPPORTED`;
`409 POSSIBLE_DUPLICATE`, `EMAIL_IN_USE`, `MOBILE_IN_USE`, `EMPLOYEE_CODE_IN_USE`,
`ALREADY_LINKED`; `403 OPERATION_NOT_ALLOWED`, `ENTITY_NOT_ALLOWED`, `PRIVILEGED_ACCOUNT_PROTECTED`
(the login has HR or admin rights: its password and sign-in details change only in HRMS);
`422 MAPPING_OTHER_COMPANY_DEPARTMENT` / `_LOCATION`.
"""
        + _LOGGED,
    ),
    "get_synced_employee": (
        "Get one synced employee",
        _KEY.format(scope="employees.read")
        + """
What HRMS holds now for the employee linked to `external_id`, limited to the fields your app is
given. Use it to check a record after a sync. `404 NOT_LINKED` if nobody is linked to it.
""",
    ),
    "exit_employee": (
        "Exit an employee",
        _KEY.format(scope="employees.sync")
        + """
Records a separation on `last_working_day`. A future date is scheduled and applied on that date.
From then on the employee can't sign in, and your app can't get a session for them. Leave,
attendance and payroll history is kept.

Needs an `Idempotency-Key` header: a retry with the same key and body returns the first
response.

**Safety valve:** if your app exits more employees in 24 hours than the company's settings allow,
further exits return `202` with outcome `HELD_FOR_REVIEW` until HR releases them.

**Outcomes:** `APPLIED`, `SCHEDULED`, `HELD_FOR_REVIEW`, `NO_CHANGE` (already separated),
`STALE_IGNORED`.
"""
        + _LOGGED,
    ),
    "rehire_employee": (
        "Rehire a separated employee",
        _KEY.format(scope="employees.sync")
        + """
Rehires the same employment from `hire_date` and reactivates the login. Department, location
and designation default to the last placement; send them to change it. Needs an
`Idempotency-Key` header. `409 NOT_SEPARATED` if the employee isn't separated.
"""
        + _LOGGED,
    ),
    "bulk_upsert": (
        "Create or update up to 200 employees",
        _KEY.format(scope="employees.sync")
        + """
The same as the single create-or-update for each record, each in its own savepoint: one bad
record doesn't stop the rest. `results` has one entry per record, in the order sent, with its
status and either the result or the error.

Send managers before their reports. A report whose manager isn't synced yet is created with a
`MANAGER_PENDING` warning and linked automatically when the manager arrives.

Needs an `Idempotency-Key` header.
"""
        + _LOGGED,
    ),
    "link_employees": (
        "Link your existing employees to HRMS employees",
        _KEY.format(scope="employees.sync")
        + """
Run once at go-live, for employees who are already in both systems. Matches each record by
`employee_code` (or `email`) to an HRMS employee not yet linked to your app.

Run it first with `dry_run: true` (the default): the report lists `matched`, `not_in_hrms`,
`ambiguous`, `already_linked`, and the HRMS employees `not_in_app`. Then run it again with
`dry_run: false` to save the links.
""",
    ),
    "reconcile": (
        "Compare your active employees with HRMS",
        _KEY.format(scope="employees.read")
        + """
Send every `external_id` your system has as active. The report lists the ones HRMS doesn't
have, active HRMS employees your system didn't list, and employees separated in HRMS but
active in yours. **It reports only; it changes nothing.** Run it weekly.
""",
    ),
    # ─── Sessions ────────────────────────────────────────────────────────────
    "issue_session": (
        "Get a session token for one employee",
        _KEY.format(scope="sessions.issue")
        + """
For employees who use HRMS through your app's screens: punching in and out, their attendance,
leave and profile, and a manager's approvals. Your server calls this after the employee has
signed in to your app, then calls the ordinary HRMS endpoints with
`Authorization: Bearer <access_token>`.

The token:

- belongs to that one employee, and sees exactly what they could see signing in to HRMS;
- never carries more than the EMPLOYEE or MANAGER role;
- works only on self-service endpoints, and only for the features the company switched on
  (otherwise `403 NOT_AVAILABLE_VIA_INTEGRATION`);
- expires after the company's session length (60 minutes by default), and stops working at
  once if your key is revoked, the employee leaves, or their password changes.

Keep the token on your server and reuse it until it is close to expiring. Punches made with it
are recorded with source `INTEGRATION` and your app's code.

An active employee who has no HRMS login yet (hired in HRMS, linked by your app) gets one
automatically, with EMPLOYEE rights and **no password**: they can use HRMS through your app, but
can't sign in to HRMS directly until HR issues credentials.

`403 SESSION_REFUSED` when no active employee is linked to the ID (the same answer for every
reason).
""",
    ),
    # ─── Read API ────────────────────────────────────────────────────────────
    "events_feed": (
        "Read the events feed",
        _KEY.format(scope="events.read")
        + """
What changed in HRMS since your last call: `employee.hired`, `employee.updated`,
`employee.manager_changed`, `employee.separated`, `employee.rehired`, `employee.hire_cancelled`,
in the order they happened. Changes your own app made are not sent back to it.

Pass the `next_cursor` from your previous call as `after` (omit it the first time). Poll every
30 to 60 seconds; an empty `events` list means you are up to date. The cursor you send confirms
you have everything before it.

Nothing is ever skipped, even when HRMS commits changes out of order, and each employee's events
arrive in order. Each event carries the employee as your app is allowed to see them, and for
updates the changed fields (`changes`, old and new).

Events are kept 30 days. If you fall further behind, the call returns `410 RESYNC_REQUIRED`:
reload with `GET /v1/integrations/employees`, then continue from the cursor in the
`X-Resync-Cursor` header.
""",
    ),
    "list_synced_employees": (
        "List employees",
        _KEY.format(scope="employees.read")
        + """
All employees your app may see, with the fields it is given, paged by `cursor`. With
`updated_since`, only employees that changed after that time. Use it for the first load and
for a full reload; then follow the events feed from `events_cursor`.
""",
    ),
    "org_reference": (
        "List companies, departments, locations or designations",
        _KEY.format(scope="org.read")
        + """
`kind` is `companies`, `departments`, `locations` or `designations`. Limited to the companies
your key covers.
""",
    ),
    "holidays": (
        "List holiday calendars for a year",
        _KEY.format(scope="org.read")
        + """
Each holiday calendar for `year`, with its holidays (and whether each is optional) and the
companies, departments or employees it applies to.
""",
    ),
    "approved_leave": (
        "List approved leave in a date range",
        _KEY.format(scope="leave.read")
        + """
Approved leave that overlaps `from`–`to` (at most a year), for the companies your key covers,
with your external ID for each employee.
""",
    ),
    "daily_attendance": (
        "Daily attendance for one date",
        _KEY.format(scope="attendance.read")
        + """
Each employee's day on `date`: status, first IN, last OUT and worked minutes, for the companies
your key covers. A day is final once its 24-hour punch window has closed.
""",
    ),
    # ─── Integration settings (admin) ────────────────────────────────────────
    "integration_catalog": (
        "Integration options",
        """
Everything the settings screens render: the field catalogue (and which fields an app can own),
the ownership presets, the key scopes, the event types, the data classes and the built-in
defaults per app kind.
""",
    ),
    "list_apps": (
        "List connected apps",
        """
Each connected app with its linked employees, active keys, last request and how far it has read
the events feed (`feed_lag` = events it hasn't confirmed yet).
""",
    ),
    "create_app": (
        "Connect an app",
        """
`code` (e.g. `ERP`, `CRM`) is how the app appears in logs, on punches and in employee badges.
`kind` is `TWO_WAY` (sends employees in and reads changes), `RECEIVE_ONLY` or `READ_ONLY`.
Then create a key for it.
""",
    ),
    "update_app": (
        "Rename, pause, resume or disconnect an app",
        """
`PAUSED` refuses the app's calls (`403 APP_PAUSED`) while events keep queuing. `DISCONNECTED`
revokes every key at once and can't be undone; the log and links stay as history.
""",
    ),
    "list_keys": ("List an app's keys", "Keys never show the secret again; only the prefix."),
    "create_key": (
        "Create an API key",
        """
**The full key is in this response only.** Store it in the app server's secret store.

- `scopes`: what the key can do (see the catalogue). A receive-only or read-only app can't hold
  write scopes.
- `allowed_ips`: addresses or CIDR ranges the key works from. Strongly recommended.
- `legal_entity_ids`: limit the key to these companies.
- An app can have two active keys, so you can switch to a new one before revoking the old.
""",
    ),
    "revoke_key": (
        "Revoke an API key",
        "Takes effect at once, including for its OAuth tokens and the employee sessions it "
        "issued. Give a reason; it is kept with the key.",
    ),
    "get_settings": (
        "The settings in force",
        """
The effective settings for the app: the tenant default, or with `legal_entity_id`, that
company's settings (the default plus the company's override). `overridden` lists what the
company changes, and `warnings` lists settings that contradict each other.
""",
    ),
    "list_profiles": (
        "Settings versions",
        "Every version of the tenant default (or of one company's override): drafts, the one in "
        "force, scheduled ones and history.",
    ),
    "create_profile": (
        "Start a settings draft",
        """
Starts a draft from the settings in force (or from a `preset`, or from `settings` you send).
For a company override, the draft holds only what the company changes. Edit it, preview it,
then publish it from a date.
""",
    ),
    "update_profile": ("Edit a settings draft", "Only a draft can be edited."),
    "discard_profile": ("Discard a settings draft", "Only a draft can be discarded."),
    "preview_profile": (
        "Preview what publishing a draft would change",
        """
Before publishing: how many linked employees it affects, which fields become locked or unlocked
in HRMS, recent HR edits to fields that would become owned by the app, events switched on or off,
lifecycle changes, and settings that contradict each other.
""",
    ),
    "publish_profile": (
        "Publish a settings draft",
        "Publishes the draft from `effective_from` (today or later). The version it replaces "
        "stays as history; publishing an earlier version again is how you roll back.",
    ),
    "list_mappings": ("List value mappings", "The app's values and the HRMS records they map to."),
    "create_mapping": (
        "Map an app's value to an HRMS record",
        "E.g. the ERP's department `Ops` to HRMS's *Operations*. A role maps to `EMPLOYEE` or "
        "`MANAGER` only.",
    ),
    "delete_mapping": ("Remove a value mapping", "Later calls with that value are matched again."),
    "unmapped_values": (
        "Values the app sent that HRMS couldn't match",
        "From refused calls in the last 90 days, not mapped since. Map each, then the app's "
        "retry succeeds.",
    ),
    "sync_log": (
        "The app's sync log",
        "Every call the app made, newest first, with the outcome, the changed fields (contact "
        "details masked), warnings and errors. Filter by `outcome`, `operation` or "
        "`external_id`; page with `before`.",
    ),
    "list_duplicates": (
        "Possible duplicates",
        "Records the app sent that look like an unlinked HRMS employee, with both side by side.",
    ),
    "resolve_duplicate": (
        "Confirm or reject a possible duplicate",
        "`SAME_PERSON` links the app's record to the HRMS employee; `DIFFERENT_PERSON` lets the "
        "app's retry create a new employee.",
    ),
    "held_exits": (
        "Exits held by the safety valve",
        "Exits the app sent beyond the company's 24-hour limit, waiting for HR.",
    ),
    "decide_held_exit": (
        "Release or reject a held exit",
        "`RELEASE` applies the exit (from its last working day, or today if that has passed). "
        "`REJECT` drops it.",
    ),
    "not_linked": (
        "Employees hired in HRMS that the app hasn't linked",
        "Hires announced to the app more than 24 hours ago with no link yet.",
    ),
    "app_report": (
        "What does this app receive?",
        "For privacy and data-minimisation reviews: the app's events, fields, data classes and "
        "people, its keys and scopes, and how many employees it has been sent.",
    ),
    "employee_field_control": (
        "Which fields a connected app manages for an employee",
        "For each field: its owner (an app's code, `SHARED` or `HRMS`), whether it is locked in "
        "HRMS, and whether HR may override it with a reason.",
    ),
}

"""Endpoint docs: Reminders (scheduled birthday and work-anniversary mail)."""

_WORDING = """
The wording is HTML from a rich-text editor, cut down to a safe set of tags on save. Put
`{variable}` where a value should appear (see `GET /v1/reminders/variables`); a variable that
does not exist is refused with `422 REMINDER_WORDING_INVALID`, so a mail never goes out with a
literal `{placeholder}`. A mail listing several people repeats the part between `{#each}` and
`{/each}` once per person.
"""

DOCS: dict[str, tuple[str, str]] = {
    "reminder_variables": (
        "Variables the wording can use",
        "The `{variable}` names for a trigger and what each one fills in. `age` is for "
        "birthdays; `years` and `joining_date` for work anniversaries; `joining_date` for joiners; "
        "`last_day` for exits.",
    ),
    "reminder_defaults": (
        "Starter wording for a new rule",
        "A ready-made subject and body for the team mail and for the person's own mail, to "
        "begin a new rule from.",
    ),
    "list_reminder_rules": (
        "List reminder rules",
        "The rules for the companies you can see. Group-wide rules are shown to group-level "
        "users only.",
    ),
    "create_reminder_rule": (
        "Create a reminder rule",
        """
Which event (`BIRTHDAY`, `WORK_ANNIVERSARY`, `NEW_JOINER` from the hire date, or `EXIT` from the
separation date), for whom (a company and department, or
everyone), how often and when. `frequency` is `SAME_DAY`, `ONE_DAY_BEFORE`, `CONTINUOUS` (every
day from `days_before` days ahead until the day), `ALTERNATE_DAYS` (every second day counting
back from `days_before`, and the day itself) or `CUSTOM` (the days in `custom_offsets`).
`send_time` is the time of day in the company's timezone. Tell the person (`notify_employee`),
their line manager (`notify_manager`), everyone in the company and department
(`notify_everyone`, never about themselves) and/or `extra_emails`. The person's own mail goes out
on the day itself only; the others follow the whole schedule. `digest` sends one mail listing
everyone due instead of one per person.

A rule saved after its time of day has passed starts tomorrow. A 29 February event is
observed on 28 February in other years. People who have left are not included, except by an
`EXIT` rule, which looks at people who have not yet left. A department also covers the
departments beneath it. `NEW_JOINER` and `EXIT` are one-off dates, not yearly.
"""
        + _WORDING,
    ),
    "get_reminder_rule": ("Get a reminder rule", "One rule with its wording."),
    "update_reminder_rule": (
        "Change a reminder rule",
        "Send only the fields that change, with the `version` you loaded: if someone saved in "
        "between, the change is refused with `409 STALE_VERSION`. Changed wording applies to "
        "mail that is queued but not yet sent; mail already sent is not changed. Pause a rule "
        "with `is_active: false`.\n" + _WORDING,
    ),
    "delete_reminder_rule": (
        "Remove a reminder rule",
        "Stops the rule and hides it. Its history and delivery log are kept.",
    ),
    "reminder_rule_history": (
        "Who changed a rule, and what",
        "Each create, edit and removal with the old and new value of every field that changed.",
    ),
    "preview_reminder_wording": (
        "Preview a draft",
        "Fills a draft subject and body with two sample people and returns the finished HTML "
        "and plain text, plus any `problems` (unknown variables) found. Nothing is sent or "
        "saved.",
    ),
    "test_send_reminder": (
        "Send a test to yourself",
        "Mails the rule's wording, filled with sample people, to your own address. Fails with "
        "`409 MAIL_DISABLED` where mail is not switched on.",
    ),
    "upcoming_reminders": (
        "Who a rule will mail about",
        "The people the rule will mail about over the next `days` (up to 90), each with the "
        "dates a mail goes out. Use it to check a rule before relying on it.",
    ),
    "reminder_deliveries": (
        "Recent reminder mail",
        "Queued, sent and failed mail with the recipient and how many attempts it took. A "
        "failed mail used all its attempts or belonged to a rule that was paused or removed.",
    ),
}

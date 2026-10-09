"""Endpoint docs: Dashboard, Reports, Platform."""

_ADMIN_ONLY = "Needs the `ADMIN` platform role. `VIEWER` admins get `403`."

DOCS: dict[str, tuple[str, str]] = {
    # ─── Dashboard ───────────────────────────────────────────────────────────
    "login_celebrations": (
        "Today's company celebrations",
        "Birthdays and completed work anniversaries in the signed-in employee's own company, "
        "plus personal wishes. The company comes from the caller's employment; no employee "
        "or company selector is accepted. Available to every authenticated tenant user, "
        "without HR dashboard access. Accounts without a current employment get empty lists. "
        "Dates use the tenant timezone; February 29 is observed on February 28 in non-leap "
        "years. Birth dates, birth years, ages and contact details are never returned.",
    ),
    "employee_dashboard": (
        "Employee dashboard",
        "Self-service home for one employee: today's attendance, this month's summary, "
        "onboarding progress and upcoming holidays. Leave out `employment_id` for the "
        "caller's own.",
    ),
    "team_overview": (
        "My team",
        "The caller's direct reports: who is in today, each person's month so far, and upcoming "
        "leave. Each report must also be visible under the caller's `people.read` scope. "
        "Returns `400` when the login isn't linked to an employee.",
    ),
    "manager_dashboard": (
        "Manager dashboard",
        "Team attendance today and the approvals waiting for a manager. Leave out "
        "`manager_employment_id` for the caller's own team.",
    ),
    "hr_dashboard": (
        "HR dashboard",
        """
Workforce figures for HR, limited to the companies the caller's `dashboard.hr` grant covers.
Pass `legal_entity_id` to narrow to one company.

**`sections`** is a comma-separated list, so you only pay for what you show. Leave it out
for all sections. The names are: `headcount`, `today`, `actions`, `pending_requests`,
`upcoming_birthdays`, `upcoming_anniversaries`, `department_distribution`,
`entity_distribution`, `recent_joiners`, `tenure`, `kyc`, `org_summary`, `trends`, `exits`,
`attendance_30d`, `vacancies`, `statutory`, `worker_types`, `leave_by_department` and
`lifecycle`. An unknown name returns `422`.
""",
    ),
    "super_admin_dashboard": (
        "Super admin dashboard",
        "The HR dashboard plus system-health indicators. It takes the same `sections` and "
        "`legal_entity_id` parameters.",
    ),
    "get_layout": (
        "Get your dashboard layout",
        "The caller's saved widget layout for `dashboard` (`hr` or `overview`), or the default "
        "one, plus the catalogue of widgets they are allowed to add.",
    ),
    "save_layout": (
        "Save your dashboard layout",
        "Saves which widgets appear, in what order and size. An unknown or duplicated widget "
        "returns `422`, and one the caller isn't allowed to use returns `403`.",
    ),
    "reset_layout": (
        "Reset your dashboard layout",
        "Deletes the caller's saved layout and returns the default one.",
    ),
    # ─── Reports ─────────────────────────────────────────────────────────────
    "report_meta": (
        "Report columns and filters",
        "The columns and filters a report on `module` can use (`ATTENDANCE`, `EMPLOYEE`, "
        "`ONBOARDING`, `LEAVE` or `HEADCOUNT`), including each filter's allowed operators. "
        "Fixed metadata, with no company data.",
    ),
    "list_reports": (
        "List saved reports",
        "Built-in (system) and custom report definitions. Filter by `owner_type` to get the "
        "reports meant for one audience. Reports shared with everyone (`ALL`) are always "
        "included.",
    ),
    "create_report": (
        "Save a custom report",
        """
Saves a report definition: a `module`, the `columns` to show (from `GET /v1/reports/meta/{module}`),
and default `filters`.

A filter is `{"field", "op", "value"}`. Operators include `eq`, `gte`, `lte`, `in` and
`between` (with a two-item `value`). Each field allows only some of them, as listed in the
metadata.
""",
    ),
    "get_report": (
        "Get a report definition",
        "One saved report: module, columns and default filters.",
    ),
    "delete_report": (
        "Delete a custom report",
        "Deletes a custom report. Built-in system reports can't be deleted (`403`). Needs "
        "`reports.write` across all companies.",
    ),
    "run_report": (
        "Run a report",
        """
Runs a saved report over the data in the caller's scope and returns the rows.

- `filters` replace the saved defaults for this run, for example a date range.
- `limit` defaults to 1,000, with a maximum of 10,000. `truncated: true` means there were
  more rows.
""",
    ),
    # ─── Platform ────────────────────────────────────────────────────────────
    "platform_login": (
        "Platform admin sign-in",
        """
Signs in a platform operator. The token only works on `/v1/platform/*`, and a tenant token is
never accepted there. If the account uses two-factor sign-in, send `otp`. Repeated failures
return `429` with `Retry-After`.
""",
    ),
    "platform_me": (
        "Who am I (platform)",
        "The signed-in platform admin's current name, email and role (`ADMIN` or `VIEWER`), "
        "read fresh from the database.",
    ),
    "forgot_password": (
        "Request a password reset",
        "Emails a reset link to a platform admin. The response is the same whether or not the "
        "email exists. Returns `503` when no email delivery is configured.",
    ),
    "reset_password": (
        "Complete a password reset",
        "Sets a new password using the `token` from the reset link. Returns `400` if the link "
        "is invalid or has expired.",
    ),
    "list_tenants": (
        "List tenants",
        "Every tenant (customer) on the platform, with status and plan. Search with `q`, and "
        "page with `limit` and `offset`. Archived tenants are only included with "
        "`include_archived=true`.",
    ),
    "get_tenant": (
        "Get a tenant",
        "One tenant's companies, status, plan and employee count.",
    ),
    "update_tenant": (
        "Suspend, reactivate or change a tenant's plan",
        f"""
Sets `status` (`ACTIVE` or `SUSPENDED`) and/or `plan` (`STARTER`, `GROWTH` or `ENTERPRISE`).
A suspended tenant's users can't sign in, and their existing sessions stop working.
{_ADMIN_ONLY}
""",
    ),
    "archive_tenant": (
        "Archive a tenant",
        f"Offboards a tenant (a soft delete). Its users can no longer sign in, and the data is "
        f"kept so the tenant can be restored. {_ADMIN_ONLY}",
    ),
    "restore_tenant": ("Restore a tenant", f"Brings an archived tenant back. {_ADMIN_ONLY}"),
    "list_admins": ("List platform admins", "Every platform admin, with role and status."),
    "create_admin": (
        "Add a platform admin",
        f"Creates a platform admin with role `ADMIN` (full control) or `VIEWER` (read-only). "
        f"{_ADMIN_ONLY}",
    ),
    "update_admin": (
        "Suspend or change a platform admin",
        f"Sets another admin's `status` or `role`, which takes effect on their next request. You "
        f"can't change your own account, or remove the last active admin (`400`). {_ADMIN_ONLY}",
    ),
    "get_audit_log": (
        "Platform audit log",
        "Every change made through the platform API, newest first, with who made it and when. "
        "Paged with `limit` and `offset`.",
    ),
    "create_company": (
        "Register a company",
        f"""
Creates a company in one of two ways:

- `mode: "NEW_TENANT"`: a new, isolated tenant with a first `SUPER_ADMIN`. Needs
  `admin_email` and `admin_password`.
- `mode: "SUBSIDIARY"`: a new legal entity inside an existing tenant (`parent_tenant_id`).

{_ADMIN_ONLY}
""",
    ),
    "platform_logout": (
        "Platform sign-out",
        "Ends every session of the platform admin's account and clears the browser cookie.",
    ),
    "platform_enroll_mfa": (
        "Start two-factor setup (platform)",
        "The same as `POST /v1/auth/mfa/enroll`, for a platform admin.",
    ),
    "platform_confirm_mfa": (
        "Confirm two-factor setup (platform)",
        "The same as `POST /v1/auth/mfa/confirm`, for a platform admin.",
    ),
}

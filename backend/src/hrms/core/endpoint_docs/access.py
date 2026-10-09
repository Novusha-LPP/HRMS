"""Endpoint docs: Auth, Users, Preferences."""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Auth ────────────────────────────────────────────────────────────────
    "login": (
        "Sign in",
        """
Exchanges a sign-in identifier and password for an access token.

`identifier` can be an email address, an employee code or a mobile number.

**Retry with extra fields when told to:**
- `409 COMPANY_REQUIRED`: the identifier exists in more than one company. Send the company
  code as `tenant`.
- `401 MFA_REQUIRED`: the account uses an authenticator app. Send the current 6-digit code as
  `otp`. A wrong or reused code returns `401 MFA_INVALID`.

**Other failures**
- `401`: wrong identifier or password. The message is the same in both cases.
- `403`: the company is suspended, or the employee has been separated.
- `429`: too many failed attempts. Wait for the number of seconds in `Retry-After`.

The response's `user` is the same as `GET /v1/auth/me`. If `user.mfa_required` is `true`, the
account must finish two-factor setup (`/v1/auth/mfa/enroll`) before other calls work.
""",
    ),
    "change_password": (
        "Change your password",
        """
Replaces the caller's password and returns a **new token**. Use the new token from now on.

- Every token issued before this call stops working, on every device.
- This works even while a password change is required (`403 PASSWORD_CHANGE_REQUIRED`).
  That state applies to imported accounts and to passwords reset by an admin.
- `new_password` must be 8 to 72 characters (bcrypt counts bytes, so non-ASCII characters
  count more) and different from the current one.

**Errors:** `400` if the current password is wrong or the new one is the same.
""",
    ),
    "register_company": (
        "Register a new company (self-service)",
        """
Creates a completely new, isolated **tenant**. It gets its own first legal entity, the five
standard roles and a `SUPER_ADMIN` login for `admin_email`. The response signs that admin in.

This does not add a company to an existing group. To do that, use
`POST /v1/org/legal-entities` while signed in to that group.

Returns `403` when self-service registration is turned off on this deployment.
""",
    ),
    "me": (
        "Who am I",
        """
The signed-in user's profile and what they can do: roles, effective permissions, whether they
can see every company (`is_all_scope`), and the companies (`legal_entities`) they can see.

Call this after sign-in, and whenever you need to decide what to show the user.
""",
    ),
    "logout": (
        "Sign out",
        """
Ends **every** session of the caller's account, not just this one. All tokens issued so far
stop working, on every device, and the browser session cookie is cleared.

An integration that shares one account across several processes should not call this as
routine cleanup. Let the token expire instead.
""",
    ),
    "enroll_mfa": (
        "Start two-factor setup",
        """
Starts authenticator-app (TOTP) setup for the caller. Requires the current `password`.

Returns `secret` and an `otpauth://` `uri`. Show the URI as a QR code, or let the user type the
secret into their authenticator app. Then call `POST /v1/auth/mfa/confirm` with the first code.
Two-factor sign-in is not active until it is confirmed.
""",
    ),
    "confirm_mfa": (
        "Confirm two-factor setup",
        """
Finishes two-factor setup with a 6-digit `code` from the authenticator app. From now on,
`POST /v1/auth/login` needs `otp` for this account.

Returns `401 MFA_INVALID` if the code is wrong or has already been used.
""",
    ),
    # ─── Users ───────────────────────────────────────────────────────────────
    "list_roles": (
        "List roles",
        """
The roles defined in this tenant and the permissions each one grants:

| Role | Meant for |
|---|---|
| `SUPER_ADMIN` | Everything (`*`) |
| `HR_MANAGER` | People, org, leave, attendance, policy, KYC, recruitment and reports |
| `MANAGER` | Approving requests for their team, and team dashboards |
| `EMPLOYEE` | Self-service only (own leave, punches, corrections, KYC) |
| `ACCOUNTANT` | Read-only people, reports and KYC |

Use a role's `name` when creating a user.
""",
    ),
    "list_users": (
        "List user accounts",
        """
User accounts (logins) the caller can manage. Each one shows its role, scope, linked employee
and status. Accounts are limited to the companies in the caller's scope.

Paged with `limit` and `offset`.
""",
    ),
    "create_user": (
        "Create a user account",
        """
Creates a login and grants it one role with a scope.

**`scope_type`** decides which records the role applies to:

| `scope_type` | Sees | Also needs |
|---|---|---|
| `ALL` | Every company in the tenant | Only a group-level admin can grant this |
| `LEGAL_ENTITY` | The listed companies | `legal_entity_ids` |
| `ALL_REPORTS` | The employee's whole reporting tree | `employment_id` |
| `DIRECT_REPORTS` | The employee's direct reports | `employment_id` |
| `SELF` | Only their own record | `employment_id` |

`employment_id` also links the login to an employee, which enables self-service.
`EMPLOYEE` can only be granted with `SELF`.

**Guards:** you can't grant a role with more permissions than you hold, or a scope wider
than your own (`403`). If `must_change_password` is `true`, the user must replace the password
at first sign-in.

**Errors:** `400` for an unknown role, missing scope fields, or an email that is already used.
""",
    ),
    "update_user": (
        "Activate or deactivate a user",
        """
Sets a login's `status` to `ACTIVE` or `INACTIVE`. `INACTIVE` blocks sign-in and ends the
user's existing sessions at once. `ACTIVE` restores access.

Returns `409` if this would deactivate the last active administrator.
""",
    ),
    "reset_user_password": (
        "Reset a user's password",
        """
Sets a temporary password. The user must replace it at their next sign-in, and until then the
API returns `403 PASSWORD_CHANGE_REQUIRED`. All of the user's existing sessions end.

Send the temporary password to the user through a channel you trust. The API doesn't email it.
""",
    ),
    "issue_sign_in_slips": (
        "Issue sign-in slips",
        """
Gives up to 100 employees temporary sign-in details at once, for staff without email who sign
in with their **employee number**. An employee login (role `EMPLOYEE`, own record only) is
created where there is none; an existing employee login gets a new temporary password and its
sessions end. Everyone must choose their own password at first sign-in.

`numeric: true` (default) makes 8-digit passwords, easy to type on a phone or kiosk.

Each result's `outcome` is `CREATED`, `RESET` or `SKIPPED` with a `reason`: people who have
left, switched-off logins, logins with more than self-service (HR, managers, admins: reset those
one at a time), your own login, and employees outside your companies are skipped.

**`temporary_password` is returned only in this response.** It is not stored in plain text,
not logged, and not shown again; print or hand out the slips straight away. The change history
records that a password was issued, never the password.
""",
    ),
    # ─── Preferences ─────────────────────────────────────────────────────────
    "get_preferences": (
        "Get your preferences",
        "The caller's colour theme and dashboard style. Defaults are returned when nothing has "
        "been saved.",
    ),
    "update_preferences": (
        "Change your preferences",
        "Updates the caller's `color_theme` and/or `dashboard_style`. Fields you leave out stay "
        "as they are.",
    ),
}

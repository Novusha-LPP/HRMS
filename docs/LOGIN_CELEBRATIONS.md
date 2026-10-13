# Login celebrations

Employees receive a welcome popup for today's birthdays and work anniversaries after signing in or restoring an authenticated session. It uses the existing theme, including light and dark mode.

## Behavior

- A birthday shows a personal birthday wish. A work anniversary shows a thank-you message with completed service years. When both occur together, one popup combines the wishes.
- Employees also see today's celebrants in their own company. Birthdays show a name and greeting; anniversaries show a name, company, and completed service years.
- Continue, Close, Escape, or clicking the backdrop acknowledges the day. The popup then stays dismissed on routes, reloads, and subsequent sign-ins in the same browser for that employee and business date.
- No celebrations means no popup. A failed celebration request does not interrupt the app. Accounts without a current employment do not request the roster.
- Password-change and MFA requirements finish before the popup can load.
- The greeting and roster scroll together on short screens and for long lists. Continue remains visible, the scroll area is keyboard accessible, and Tab stays inside the dialog.

## Date and company rules

`GET /v1/dashboard/celebrations` uses the tenant's configured timezone, existing date of birth, and employment hire date. The current employee's company is derived on the server; clients cannot select another company. Current, non-archived employees in an active company are eligible. An anniversary starts after one completed year. February 29 birthdays and hire dates are celebrated on February 28 in a non-leap year, matching the existing upcoming-highlights convention.

The response contains today's business date, personal flags, and the minimal celebration roster. It does not return full dates of birth, birth years, ages, or contact details. Tenant isolation and database row-level security apply. The browser stores only the acknowledged business date, keyed by tenant, account, and employment. Blocked browser storage falls back to memory for the current page session.

## Assumptions to review

- Colleagues means the employee's current company, rather than every company in the tenant.
- Daily acknowledgment is local to a browser; another browser or device can show the same day's wishes again.
- The popup provides automatic wishes inside the app. It does not send email or messages.
- Employee dates must already be recorded correctly. Opening a new authenticated session checks today's events; an app kept open overnight does not poll for a new date.

## Verification

- Backend cases cover employee/manager/HR access, company and tenant isolation, no birth-date disclosure, leap days, current employment filters, duplicate birthdays, no-employment accounts, and timezone boundaries.
- Browser cases cover real fixture sign-in, birthday/anniversary/combined wishes, colleague lists, daily acknowledgment and identity isolation, unavailable storage, empty/error responses, authentication gates, keyboard controls, long lists, long names, and short phone landscape screens.
- The popup is checked in all three themes in light and dark mode on desktop and phone, including WCAG AA text and icon contrast. Existing theme regressions are also checked.

Run the browser suite with `npx playwright test --config=playwright.celebrations.config.ts` from `frontend/`. It builds a local preview and intercepts APIs with synthetic employee data. Run backend cases with `pytest tests/test_login_celebrations.py` from `backend/` against a disposable test database configured with the application's restricted role.

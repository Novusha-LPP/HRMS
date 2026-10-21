"""Endpoint docs: Organisation, People, Onboarding, Employee KYC."""

_HISTORY = """
The change history of this record, newest first: who changed which fields, from what, to what,
and when. Needs the same visibility as reading the record.
"""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Organisation ────────────────────────────────────────────────────────
    "list_legal_entities": (
        "List companies (legal entities)",
        """
The legal entities (companies) in the tenant that the caller can see. Archived ones are left
out. A user scoped to particular companies sees only those.
""",
    ),
    "create_legal_entity": (
        "Create a company",
        """
Adds a legal entity (a sister company) to the caller's tenant. Only a group-level
administrator (a role with `ALL` scope) can do this.

`financial_year_start_month` is 1–12 (for example `4` for April). Leave it out to use the
default.
""",
    ),
    "update_legal_entity": (
        "Update a company",
        "Renames or reconfigures a legal entity. Only fields you send are changed. Needs a "
        "group-level administrator. Every change is recorded in the entity's history.",
    ),
    "legal_entity_history": ("Company change history", _HISTORY),
    "list_locations": (
        "List locations",
        "Offices, plants and sites the caller can see, with address, time zone and the "
        "company they belong to.",
    ),
    "create_location": (
        "Create a location",
        """
Creates a work location. `timezone` is an IANA name (for example `Asia/Kolkata`). Set
`legal_entity_id` to tie the location to one company. The caller must have that company in
scope.
""",
    ),
    "update_location": (
        "Update a location",
        "Changes a location's details. The head, lead and PM (`*_employment_id`) are the people "
        "responsible for the site. Only fields you send are changed.",
    ),
    "location_history": ("Location change history", _HISTORY),
    "list_org_units": (
        "List departments and teams",
        """
Org units the caller can see. `type` tells them apart:
- `DEPARTMENT_TEMPLATE`: a shared department in the group-wide list.
- `DEPARTMENT`: a shared department assigned to one company.
- `TEAM`: a team inside a company's department.
""",
    ),
    "create_org_unit": (
        "Create a department or team",
        """
Creates an org unit.

- **`DEPARTMENT_TEMPLATE`:** a shared department in the group-wide list. It needs a group
  administrator, takes no `legal_entity_id` or `parent_id`, and its name must be unique
  (`409`). To use it in a company, call `POST /v1/org/legal-entities/{entity_id}/departments`.
- **`TEAM`:** `parent_id` must be a company's `DEPARTMENT`, and the team must belong to the
  same company (`422` otherwise).

`head_employment_id` names a department's head. `lead_employment_id` and `pm_employment_id`
name a team's lead and project manager. `effective_from` is the date the unit starts.
""",
    ),
    "assign_departments": (
        "Assign departments to a company",
        """
Makes shared departments (`DEPARTMENT_TEMPLATE` IDs) available in a company. Each one
becomes a `DEPARTMENT` of that company, where employees and teams can be placed. Returns the
company's departments after the change.
""",
    ),
    "update_org_unit": (
        "Update a department or team",
        """
Renames or recodes an org unit, or changes who heads it. A shared department's `type` can't
change, and its name must stay unique. To rename a company's `DEPARTMENT`, edit its shared
department instead (`409`).
""",
    ),
    "org_unit_history": ("Department change history", _HISTORY),
    "list_jobs": (
        "List jobs",
        "Job titles defined for the tenant, for example *Accounts Executive*. Employees are "
        "given one through a personnel action.",
    ),
    "create_job": ("Create a job", "Adds a job title. `code` and `function` are optional."),
    "update_job": ("Update a job", "Changes a job's title, code or function."),
    "job_history": ("Job change history", _HISTORY),
    "list_grades": (
        "List grades",
        "The tenant's grades or levels (for example *W1*, *M2*), lowest `sequence` first. "
        "Includes inactive ones, so old records still show their grade.",
    ),
    "create_grade": (
        "Create a grade",
        "Adds a grade. `code` must be unique in the tenant, ignoring case (`409`). `sequence` "
        "orders grades from junior to senior.",
    ),
    "update_grade": (
        "Update a grade",
        "Changes a grade's code, name or order. Grades are never deleted: set `status` to "
        "`INACTIVE` to stop using one.",
    ),
    "grade_history": ("Grade change history", _HISTORY),
    "list_cost_centres": (
        "List cost centres",
        "The tenant's cost centres, by code. Includes inactive ones.",
    ),
    "create_cost_centre": (
        "Create a cost centre",
        "Adds a cost centre. `code` must be unique in the tenant, ignoring case (`409`).",
    ),
    "update_cost_centre": (
        "Update a cost centre",
        "Changes a cost centre's code or name. Cost centres are never deleted: set `status` to "
        "`INACTIVE` to stop using one.",
    ),
    "cost_centre_history": ("Cost centre change history", _HISTORY),
    "list_positions": (
        "List positions",
        """
Positions (approved seats) in the departments and teams the caller can see, optionally for one
`org_unit_id`. Each shows its job, grade, `max_headcount`, how many current employees fill it,
and the resulting `vacancies`. Positions without a `max_headcount` have no vacancy count.
""",
    ),
    "create_position": (
        "Create a position",
        """
Adds a position to a company's department or team (not a shared department, `422`). `job_id`
and `grade_id` are optional. `max_headcount` makes it count towards the vacancies figure.
`effective_from` defaults to today.
""",
    ),
    "update_position": (
        "Update a position",
        """
Changes a position's title, code, job, grade, headcount or end date. Its department can't
change: create a new position instead. Set `status` to `INACTIVE` to retire it; positions are
never deleted.
""",
    ),
    "position_history": ("Position change history", _HISTORY),
    "list_employee_id_schemes": (
        "List employee ID schemes",
        "The rules for generating employee numbers, for example `SFPL-0042`. There is one for "
        "the whole tenant, and optionally one per company that overrides it.",
    ),
    "create_employee_id_scheme": (
        "Create an employee ID scheme",
        """
Defines how employee numbers are generated when a hire doesn't supply one: `prefix`,
`separator`, zero-padded `number_digits`, and the `next_number` to issue.

Without `legal_entity_id`, it is the tenant-wide scheme, which needs a group-level
administrator. Only one active scheme is allowed per company (`400` otherwise).
""",
    ),
    "update_employee_id_scheme": (
        "Update an employee ID scheme",
        "Changes the format or the next number. Numbers already issued are not changed.",
    ),
    "delete_employee_id_scheme": (
        "Remove an employee ID scheme",
        "Removes the scheme. New hires in that company fall back to the tenant-wide scheme, or "
        "must supply `employee_number` if there is none.",
    ),
    # ─── People ──────────────────────────────────────────────────────────────
    "create_person": (
        "Create a person",
        """
Creates the **person**: the individual and their personal details. This is step 1 of a hire.
Step 2 is `POST /v1/employees`, which creates their employment in a company.

A person can have more than one employment over time (for example, a rehire or a move between
group companies).
""",
    ),
    "list_persons": (
        "List persons",
        "Persons with an employment the caller can see. Paged with `limit` and `offset`.",
    ),
    "get_my_profile": (
        "Get your profile",
        "The caller's own personal details: legal and preferred name, date of birth, gender, "
        "nationality, email and mobile. Returns `400` when the login isn't linked to an "
        "employee.",
    ),
    "update_my_profile": (
        "Update your profile",
        "Lets employees update their own preferred name, date of birth, gender, nationality "
        "and mobile number. Fields you leave out are not changed.",
    ),
    "create_employment": (
        "Hire: create an employment",
        """
Creates an employment for an existing person in a company (`legal_entity_id`), starting on
`hire_date`.

- `employee_number` is generated from the company's employee ID scheme when you leave it out.
  If no scheme exists, it is required (`400`).
- Place the new employee in a department, location and job next, with a `HIRE` personnel
  action.

Returns `403` when the caller can't hire into that company.
""",
    ),
    "list_employees": (
        "List employees",
        """
Employees the caller can see, with their current department, job, location and manager.

- Filter by state with `filter[status]`: `ACTIVE`, `PROBATION`, `NOTICE`, `ON_HOLD` or
  `SEPARATED`.
- Paged with `limit` and `offset`.
- Personal details are only included for callers allowed to see them.
""",
    ),
    "get_employee": (
        "Get an employee",
        "One employee's current employment: company, department, job, location, manager and "
        "state. Returns `404` when the employee doesn't exist or is outside the caller's scope.",
    ),
    "preview_rejoin": (
        "Preview a rejoin",
        """
What rejoining on `effective_date` (default today) would do for someone who has left. Nothing
is changed.

- **`mode`:** `CONTINUE` keeps earlier service and any leave still held; `FRESH` starts over and
  lapses unused leave. Without `mode`, the company's rejoin policy decides.
- **`allowed_modes` and `blocked`:** a break longer than the policy's limit, or gratuity paid at
  exit, rules out `CONTINUE` unless HR records `break_condoned` with a reason.
- **`leave`:** each unused balance and whether it is kept or lapses.
- `can_proceed` is false while anything is in `blocked`.
""",
    ),
    "employment_history": (
        "Employment history",
        "Each stint of this employment, newest first: when they joined and left, why, whether "
        "gratuity was paid, and for a rejoin how it was decided (continue or start fresh, the "
        "break, and the reason). `continuity_start_date` is where service for leave eligibility "
        "counts from.",
    ),
    "list_person_employments": (
        "List a person's employments",
        "Every employment the person has had in companies you can manage, with whether each can "
        "be rejoined (they have left). Hiring someone who already has an employment is refused "
        "with `PAST_EMPLOYMENT_EXISTS` unless `confirm_new_employment` is set, so check here "
        "first and rejoin the earlier employment when that is what is happening.",
    ),
    "list_rejoin_policies": (
        "List rejoin policies",
        "How each company treats people who rejoin: the default choice and the longest break "
        "that may still continue. With no policy, rejoining continues earlier service.",
    ),
    "create_rejoin_policy": (
        "Add a rejoin policy",
        """
Sets, from `effective_from`, whether a rejoin continues earlier service (`CONTINUE`) or
starts fresh (`FRESH`) by default, and `force_fresh_after_days`, the longest break that may
continue without HR recording that it was condoned. Leave `legal_entity_id` blank for every
company; a company's own policy wins over that one. Two live policies can't start on the same
date for the same company (409).
""",
    ),
    "archive_rejoin_policy": (
        "Remove a rejoin policy",
        "Archives the policy. Rejoins already recorded keep what was decided for them.",
    ),
    "create_personnel_action": (
        "Apply a personnel action",
        """
The only way to change an employment: hire placement, transfer, promotion, manager change,
confirmation, notice, separation, and so on.

- **`effective_date` today or earlier:** applied at once.
- **`effective_date` in the future:** stored as `SCHEDULED`, and applied automatically on that
  date. Cancel it with `POST /v1/personnel-actions/{action_id}/cancel`.

**`changes`** holds the new values, as typed IDs: `org_unit_id`, `location_id`, `job_id`,
`grade_id`, `position_id`, `cost_centre_id` and `manager_employment_id`. Fields you leave out
keep their current value. The first placement must include `org_unit_id`, `location_id` and
`job_id`.

**Status rules:** `CONFIRM` and `EXTEND_PROBATION` need an employee on probation;
`PLACE_ON_NOTICE` needs a confirmed, probation or on-hold employee; `SEPARATION` needs anyone
not already separated; `REHIRE` needs a separated employee. Otherwise `409`. A scheduled
action is checked on its date and parked as `FAILED` if the rule no longer holds.
`CHANGE_JOB` is a designation change that isn't a promotion.

Send an `idempotency_key` so that a retried request is not applied twice.
""",
    ),
    "list_personnel_actions": (
        "List personnel actions",
        "An employee's personnel actions, latest effective date first, including scheduled and "
        "failed ones. "
        "A `FAILED` action shows why it couldn't be applied on its date.",
    ),
    "cancel_personnel_action": (
        "Cancel a scheduled personnel action",
        """
Stops a `SCHEDULED` (or `FAILED`) action from being applied. An `APPLIED` action is history
and can't be cancelled (`409`). To correct one, apply a new action instead.
""",
    ),
    # ─── Onboarding ──────────────────────────────────────────────────────────
    "onboarding_list_templates": (
        "List onboarding templates",
        "Checklist templates, with their items. The template marked `is_default` is used when "
        "a case is started without one.",
    ),
    "onboarding_create_template": (
        "Create an onboarding template",
        "Creates a checklist template with its `items` (title, `assignee_type`, "
        "`due_days_from_hire`, `required`, `sequence`). There is only one default: "
        "`is_default` clears it elsewhere, and the first active checklist is the default anyway.",
    ),
    "replace_onboarding_template": (
        "Save a new version of an onboarding checklist",
        """
Replaces a checklist's name, description, default flag and items. The old version is retired
and a new one is returned, with a new ID. Onboarding already started keeps the items it was
given; only cases started afterwards use the new version. A default checklist stays the default.
""",
    ),
    "deactivate_onboarding_template": (
        "Stop using an onboarding checklist",
        "Retires a checklist so it can't be chosen for new cases. The default checklist can't be "
        "retired (`409`): make another one the default first.",
    ),
    "create_standard_onboarding_template": (
        "Add the standard onboarding checklist",
        "Adds the platform's ready-made ten-item checklist (documents, bank details, policies, "
        "IT setup, induction) as a starting point to edit. It becomes the default if there is "
        "none.",
    ),
    "create_case": (
        "Start onboarding for a new hire",
        "Creates an onboarding case for an employee, with a copy of the template's checklist. "
        "Without `template_id`, the default template is used.",
    ),
    "list_cases": (
        "List onboarding cases",
        "Onboarding cases the caller can see, with checklist progress. Pass `employment_id` to "
        "see one employee's cases.",
    ),
    "get_case": ("Get an onboarding case", "One onboarding case with every checklist item."),
    "update_item": (
        "Update a checklist item",
        """
Sets a checklist item's `status`, with optional `notes` and a `document_key`.

- Employees can update items in their own case, and managers can update items for their team.
  HR (`onboarding.write`) can update any item in their scope.
- Only HR can mark a **required** item `SKIPPED`.
- When every required item is `COMPLETED` or `SKIPPED`, the case completes automatically.
- A cancelled case can't be changed (`409`).
""",
    ),
    # ─── Employee KYC ────────────────────────────────────────────────────────
    "get_my_kyc": (
        "Get your KYC record",
        "The caller's own KYC details (identity numbers, bank account, emergency contact, "
        "addresses) and uploaded documents, unmasked.",
    ),
    "update_my_kyc": (
        "Update your KYC details",
        """
Saves the caller's own KYC fields. Only fields you send are changed.

Any change sets the record back to `DRAFT` and clears an earlier verification. Call
`POST /v1/kyc/me/submit` again afterwards.
""",
    ),
    "submit_my_kyc": (
        "Submit your KYC for verification",
        "Marks the caller's KYC as `SUBMITTED`, so it appears in HR's review queue.",
    ),
    "upload_my_document": (
        "Upload a KYC document",
        """
Uploads a document for the caller, as `multipart/form-data`.

- `document_type`: `PAN_CARD`, `AADHAAR_FRONT`, `AADHAAR_BACK`, `BANK_PROOF`, `PHOTO`,
  `ADDRESS_PROOF`, `EDUCATION_CERT`, `EXPERIENCE_LETTER`, `PAYSLIP` or `OTHER`.
- Files must be PDF, PNG or JPEG (`415` otherwise), up to the upload limit (10 MB by default,
  `413` otherwise).
- The document starts as `PENDING`, and the KYC record goes back to `DRAFT`.
""",
    ),
    "get_kyc_summary": (
        "KYC summary",
        "Counts for the caller's scope: verified, waiting for review, incomplete and rejected. "
        "Needs `kyc.read`.",
    ),
    "list_employees_kyc": (
        "List employees' KYC status",
        """
Each employee's KYC status and document counts. Records waiting for review are listed first.
Needs `kyc.read`.

- `status`: `SUBMITTED`, `VERIFIED`, `REJECTED`, `ACTION_REQUIRED`, `DRAFT`, `NOT_SUBMITTED`,
  or `INCOMPLETE` (not yet submitted, draft, or action required).
- `search` matches the employee number or name.
""",
    ),
    "get_employee_kyc": (
        "Get an employee's KYC record",
        """
An employee's full KYC record and documents. Needs `kyc.read`.

Identity and bank numbers are **masked** (for example `••••••234F`) unless the caller has
`kyc.verify` or `kyc.write`. Every view is written to the access log.
""",
    ),
    "get_employee_kyc_access_log": (
        "KYC access log",
        "Who opened this employee's KYC record or documents, and when, newest first.",
    ),
    "update_employee_kyc": (
        "Update an employee's KYC details",
        "HR edits an employee's KYC fields. Needs `kyc.write` (or `people.write`). Only fields "
        "you send are changed.",
    ),
    "upload_employee_document": (
        "Upload a document for an employee",
        "HR uploads a KYC document for an employee. The same types and file rules apply as for "
        "`POST /v1/kyc/me/documents`. Needs `kyc.write` (or `people.write`).",
    ),
    "verify_document": (
        "Verify or reject a document",
        "Sets one document to `VERIFIED` or `REJECTED`. Give a `rejection_reason` when "
        "rejecting. Needs `kyc.verify` (or `people.write`).",
    ),
    "verify_overall_kyc": (
        "Verify or reject a KYC record",
        """
Records HR's decision on the whole KYC record: `VERIFIED`, `REJECTED` or `ACTION_REQUIRED`
(the employee must fix something). Give a `rejection_reason` for the last two. Needs
`kyc.verify` (or `people.write`).
""",
    ),
    "delete_document": (
        "Delete a KYC document",
        """
Deletes a document. Employees can delete their own documents unless they are already
`VERIFIED` (`400`). HR needs `kyc.write` (or `people.write`). The KYC record goes back to
`DRAFT`.
""",
    ),
    "download_document": (
        "Download a KYC document",
        """
Returns the file as an attachment. Employees can download their own documents. Anyone else
needs `kyc.verify` or `kyc.write`, because a scan shows the numbers that are otherwise masked,
and their access is written to the employee's access log.
""",
    ),
    "preview_document": (
        "Preview a KYC document",
        "The same as download, but served inline so a browser can display it.",
    ),
    "set_employee_photo": (
        "Set or replace a profile photo",
        """
Replaces the person's profile photo with the PNG or JPEG you send (`415` for anything else,
`422` if the image cannot be read, `413` over the upload limit). Any earlier photo and its
thumbnail are removed. You can change your own; changing someone else's needs `kyc.write`
(or `people.write`) over them. The new photo starts as `PENDING` and does not reset the
employee's KYC verification.
""",
    ),
    "remove_employee_photo": (
        "Remove a profile photo",
        "Deletes the person's profile photo and its thumbnail; the app goes back to initials. "
        "Same access as setting it: your own, or `kyc.write` / `people.write` over them.",
    ),
    "employee_photo": (
        "A person's profile photo",
        """
Returns the person's current profile photo (their `PHOTO` document, unless HR rejected it) as a
small square JPEG, for avatars. Add `?size=large` for the whole picture (at most 640 pixels
on its longer side), to look at it. The thumbnail is made on first use and kept encrypted next to
the original. Only the photo is served here, never the other identity documents.

You can always see your own. For anyone else you need `people.read` over that person. `204`
when there is no photo, in which case the app shows initials. The response carries an `ETag`;
send it back as `If-None-Match` to get `304` while the photo is unchanged.
""",
    ),
}

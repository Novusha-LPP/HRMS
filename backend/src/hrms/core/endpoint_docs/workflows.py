"""Endpoint docs: Approval workflows, Recruitment."""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Approval workflows ──────────────────────────────────────────────────
    "flows": (
        "List approval flows",
        "Approval flows the caller administers (needs `approvals.manage`). Each flow has its "
        "request type, the department, team or employee it applies to, its ordered stages and "
        "approvers, and a `version` for safe editing.",
    ),
    "directory": (
        "List people who can approve",
        """
Active user accounts that can be chosen as approvers or delegates.

Without `instance_id`, this needs `approvals.manage`. With `instance_id`, it is for choosing
temporary cover on that request, and the caller must be allowed to delegate one of its stages.
""",
    ),
    "create_flow": (
        "Create an approval flow",
        """
Defines a reusable, ordered approval chain for one `request_type`: `LEAVE`,
`LEAVE_CANCELLATION`, `CORRECTION`, `OVERTIME` or `JOB_REQUISITION`. Needs `approvals.manage`.

- New flows must be `reusable: true` (`422` otherwise). A flow does nothing until it is
  assigned to employees with `PUT /v1/approvals/employees/{employment_id}/flows/{request_type}`.
  An employee's assigned flow is what routes their requests.
- **`steps`** run in order, with up to 50. Each step either names approver accounts
  (`approver_source: "PEOPLE"` with `approver_ids`), or uses the employee's team lead or PM
  (`TEAM_LEAD` or `TEAM_PM`). One approval from any approver completes a step. The requester
  is never their own approver.
- Without an assigned flow, the leave type's or attendance policy's own approval settings
  apply.

Submitted requests keep the chain they started with, so editing a flow only affects new ones.
""",
    ),
    "update_flow": (
        "Update an approval flow",
        """
Replaces a flow's name, stages and enabled flag. Send the `version` you loaded. If someone
else saved in the meantime, you get `409`, so reload and try again.

The request type and the department or team can't change (`422`). Requests already
submitted keep their original chain.
""",
    ),
    "inbox": (
        "Approval inbox",
        "Requests the caller can see in approvals: ones they raised, ones where they are an "
        "approver or an active delegate, and, with `approvals.manage`, requests in their scope. "
        "Each one shows its current stage.",
    ),
    "request_detail": (
        "Get an approval request",
        "One request's full chain: stages, approvers, decisions with comments and times, "
        "delegations, and which actions the caller can take now.",
    ),
    "decide": (
        "Approve or reject a request",
        """
Records `APPROVE` or `REJECT` at the request's **current** stage. Approving the last stage
completes the underlying leave, correction, overtime or opening. A rejection at any stage
rejects it.

You can't decide your own request, decide out of order, or decide twice. A request that is
no longer pending, or was superseded, returns `409`.
""",
    ),
    "delegate": (
        "Assign temporary cover",
        """
Lets `delegate_user_id` approve for `original_user_id` at stage `level`, between
`valid_from` and `valid_until`. A `reason` is required.

- An approver at a later stage, or a workflow administrator, can arrange this.
- `flow_wide: true` covers that stage on every request of the same flow during those dates.
  Only workflow administrators can set it.
- The delegate can't be the requester, the original approver, or someone already in the chain.
""",
    ),
    "delegations": (
        "List delegations on a request",
        "Temporary cover arranged for a request, including expired and revoked cover.",
    ),
    "revoke": (
        "Revoke a delegation",
        "Ends temporary cover at once. Only the person who arranged it, or a workflow "
        "administrator, can revoke it.",
    ),
    "employee_flows": (
        "Get an employee's approval flows",
        "The reusable flows assigned directly to one employee, by request type, and whether "
        "the caller can change them.",
    ),
    "assign_employee_flow": (
        "Assign a flow to an employee",
        """
Sets the reusable flow that routes this employee's requests of `request_type`. Send
`flow_id: null` to remove it, so the leave type's or policy's own approval settings apply
again.

Send the `version` you loaded. A concurrent change returns `409`. The flow must be enabled,
reusable, available to the employee's company, and have named approvers (`422`).
""",
    ),
    # ─── Recruitment ─────────────────────────────────────────────────────────
    "access": (
        "Your recruitment access",
        "What the caller can do in recruitment (raise openings, recruit, approve) and for which "
        "units, plus lookups for the opening form. Call this first to decide what to show.",
    ),
    "get_stages": (
        "Get pipeline stages",
        "The tenant's candidate pipeline, in order. Each stage has an `outcome`: `ACTIVE` (in "
        "progress), `HIRED`, `REJECTED` or `WITHDRAWN`.",
    ),
    "put_stages": (
        "Replace pipeline stages",
        """
Saves the full list of stages: names, colours, order and outcomes. Needs recruiter access to
every company.

A stage you leave out is archived, and candidates in it stay there. A stage's outcome can't
change while it has candidates (`409`).
""",
    ),
    "list_openings": (
        "List job openings",
        "Openings the caller can see: ones they raised or manage the hiring for, and every "
        "opening in their scope when they are a recruiter. Filter by `status`, search with `q`, "
        "or pass `mine=true` for the caller's own.",
    ),
    "create_opening": (
        "Raise a job opening",
        """
Creates a job opening (requisition) for a department or team (`org_unit_id`). Department
heads, team leads and PMs can raise openings for their units, and so can recruiters.

It is saved as `DRAFT` unless you pass `submit=true`, which submits it for approval straight
away (see `POST /v1/recruitment/openings/{opening_id}/submit`).
""",
    ),
    "get_opening": (
        "Get a job opening",
        "Full details of one opening: status, positions filled, and the approval state. Salary "
        "ranges are only shown to recruiters.",
    ),
    "update_opening": (
        "Update a job opening",
        "Replaces the opening's details. Send the `version` you loaded. A concurrent change "
        "returns `409`.",
    ),
    "delete_opening": (
        "Delete a job opening",
        "Deletes a `DRAFT` or `REJECTED` opening. Close a live one instead (`409`). Only the "
        "requester or a recruiter can delete it.",
    ),
    "submit_opening": (
        "Submit an opening for approval",
        """
Sends a draft (or rejected) opening for approval:

1. If a `JOB_REQUISITION` approval flow applies to the requester's team, it is used.
2. Otherwise, if the submitter can approve openings for that company, it opens at once.
3. Otherwise, anyone with `recruitment.approve` for the company can approve it.
""",
    ),
    "withdraw_opening": (
        "Withdraw an opening",
        "Pulls an opening that is waiting for approval back to `DRAFT`. Only the requester or "
        "a recruiter can do this.",
    ),
    "decide_opening": (
        "Approve or reject an opening",
        "Records an approver's decision. Approving makes the opening `OPEN`. Rejecting needs "
        "`comments`, which the requester sees. Nobody can approve their own opening.",
    ),
    "change_status": (
        "Hold, close or reopen an opening",
        """
Moves a live opening between `OPEN`, `ON_HOLD` and `CLOSED`. Recruiters only.

An opening becomes `FILLED` by itself when every position is hired, and reopens if a hire is
moved back. Only some transitions are allowed (`409` otherwise).
""",
    ),
    "opening_events": (
        "Opening history",
        "Everything that happened to an opening, newest first: edits, approvals, status changes "
        "and candidate moves.",
    ),
    "recruitment_list_applications": (
        "List an opening's candidates",
        "The candidates in an opening's pipeline, with their stage and rating.",
    ),
    "add_application": (
        "Add a candidate to an opening",
        """
Puts a candidate into an `OPEN` opening's pipeline. Either give an existing `candidate_id`
from the talent pool, or a new `candidate`. New candidates are matched to existing ones by
email.

`stage_id` (an `ACTIVE` stage) defaults to the pipeline's entry stage. A candidate can be in
an opening only once (`409`). Recruiters only.
""",
    ),
    "get_application": (
        "Get a candidate's application",
        "One application: candidate profile, stage, rating, notes and timeline. Current and "
        "expected CTC are only shown to recruiters.",
    ),
    "update_application": (
        "Rate a candidate",
        "Sets the application's `rating`, or clears it with `clear_rating: true`. Recruiters only.",
    ),
    "move_application": (
        "Move a candidate to another stage",
        """
Moves the application to `stage_id`. Recruiters only.

- A `reason` is required for `REJECTED` and `WITHDRAWN` stages.
- Send `expected_version` so that a move someone else made first returns `409`, rather than
  being overwritten.
- Moving to a `HIRED` stage counts towards positions. When every position is filled, the
  opening becomes `FILLED`, and further hires return `409`.
""",
    ),
    "add_note": (
        "Add feedback",
        "Adds a feedback note to the candidate's timeline. Recruiters, the hiring manager and "
        "the requester can do this.",
    ),
    "link_hire": (
        "Link a hired candidate to an employee",
        "Records the employee created for a candidate in a `HIRED` stage. After this, the "
        "candidate's stage is final. Needs `people.write` for the employee's company.",
    ),
    "list_candidates": (
        "Browse the talent pool",
        "Every candidate in the tenant, de-duplicated by email. Search with `q`. Paged with "
        "`limit` and `offset`. Recruiters only.",
    ),
    "get_candidate": (
        "Get a candidate",
        "A candidate's profile: contact details, experience, links, skills, source and "
        "resume. CTC is only shown to recruiters.",
    ),
    "update_candidate": (
        "Update a candidate",
        "Replaces the candidate's profile. Send the `version` you loaded. The email must stay "
        "unique in the pool (`409`).",
    ),
    "delete_candidate": (
        "Delete a candidate",
        "Erases a candidate (for example, on their request), with their applications and resume. "
        "A candidate who became an employee can't be deleted (`409`).",
    ),
    "upload_resume": (
        "Upload a resume",
        "Uploads a resume as `multipart/form-data`. It must be PDF or Word (`415`) and within "
        "the upload limit (`413`). It replaces any earlier resume, and is stored encrypted.",
    ),
    "delete_resume": ("Delete a resume", "Removes the candidate's resume."),
    "download_resume": (
        "Download a resume",
        "Returns the resume file. Pass `inline=true` to have it displayed in the browser "
        "instead of downloaded.",
    ),
}

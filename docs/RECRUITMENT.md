# Recruitment

Department heads, team leads and PMs raise **job openings**. Openings are approved, then HR
works them through a **configurable candidate pipeline** until a candidate becomes an
employee.

## Who can do what

| Person | How they qualify | What they can do |
|---|---|---|
| Requester | Head of a department, or lead/PM of a team (`org_units.head/lead/pm_employment_id`, including units beneath it). Roles with `recruitment.request` (MANAGER) can also raise openings for their own unit. | Raise, edit and submit openings for those units. See their openings, the candidates in them, resumes and links. Leave feedback. |
| Hiring manager | Named on the opening (defaults to the requester) | Same view as the requester, plus feedback. |
| Recruiter | `recruitment.read` / `recruitment.manage` (HR_MANAGER), scoped to the companies their role covers | Everything above, plus: add candidates, move them between stages, rate them, upload resumes, see CTC, hold/close/reopen openings, browse the talent pool, link hires. |
| Approver | A configured approval flow, or `recruitment.approve` for the company | Approve or reject pending openings. |

Requesters and hiring managers never see current or expected CTC. Pipeline stages are tenant-wide,
so only recruiters with all-company access can change them.

## Opening lifecycle

```
DRAFT ──submit──▶ PENDING_APPROVAL ──approve──▶ OPEN ⇄ ON_HOLD
  ▲                 │        │                   │  ▲
  └──withdraw───────┘        └──reject──▶ REJECTED (edit, resubmit)
                                        OPEN ──all positions hired──▶ FILLED ──reopen──▶ OPEN
                               OPEN / ON_HOLD / FILLED ──close──▶ CLOSED ──reopen──▶ OPEN
```

Approval routing on submit:
1. If an approval flow for **Job opening** (`JOB_REQUISITION`) applies to the requester's team, it is used (`approval_mode = FLOW`). Decisions are made in **Workforce → Approvals** or on the opening itself. Flows are configured in Settings → Approval flows, or per employee.
2. Otherwise, if the submitter may approve openings for that company, the opening goes live straight away (`AUTO`, recorded in the history).
3. Otherwise any holder of `recruitment.approve` for the company approves it (`HR`). Nobody can approve their own request.

A reject must give a reason. The requester sees it, edits the opening and submits again.

## Candidate pipeline

- **Stages** are configured under Recruitment → Pipeline stages: name, colour, order and **outcome**.
  The outcome is what the system acts on:
  - `ACTIVE` — still in progress.
  - `HIRED` — counts towards positions and unlocks *Create employee*.
  - `REJECTED` / `WITHDRAWN` — a reason is required.
- **Defaults:** Applied → Screening → Shortlisted → Interview → Selected → Offer released → Onboarding (hired) · Rejected · Withdrawn.
- **Removing a stage** archives it. Candidates already in it stay put. A stage's outcome can't change while candidates are in it.
- **Candidates** belong to a tenant-wide talent pool. The pool is de-duplicated by email, so one person can be in several openings.
  - **Links:** LinkedIn, GitHub, portfolio, website and others, validated as http(s).
  - **Skills, source and notice period** are recorded on the profile.
  - **Resume:** PDF or Word, sniffed by content and stored encrypted through `core/document_store.py`.
- **Moving candidates:** drag-and-drop on the board (mouse, touch or keyboard) or the stage selector.
  Moves carry the application version, so concurrent moves get a 409 instead of overwriting each other.
- **FILLED:** reaching the number of positions marks the opening FILLED; dropping below it reopens the opening.
- **Hiring:** *Create employee* opens the standard Add employee sheet, prefilled from the opening.
  It creates the employment, places it (HIRE action), starts onboarding, and links the employee back to the application.
  A linked candidate's stage is final.

Every change is written to `recruitment_events`: the opening history, each candidate's timeline and their feedback notes.

## Data and API

- **Migration:** `0043_recruitment.py` adds five tables: `recruitment_stages`, `job_openings`, `candidates`, `job_applications` and `recruitment_events`.
  - Every table has tenant row-level security.
  - Foreign keys are composite and include `tenant_id`.
  - The migration is additive and needs no data backfill.
- **API:** `/v1/recruitment/*`. The module docstring in `modules/recruitment/router.py` lists the endpoints.
- **Access rules:** `modules/recruitment/access.py`.
- **Tests:** `backend/tests/test_recruitment.py` covers requisition approval (HR and configured flow), visibility, pay masking, resume handling, stage moves and concurrency, FILLED/reopen, stage configuration, and the hire link.

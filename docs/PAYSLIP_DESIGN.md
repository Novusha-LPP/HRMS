# Payslips with company branding — design

**Status:** Phase A (setup) built 2026-10-29 on branch `feature/payslip-branding`, migration 0075.
Phase B (real payslips) waits for the pay run engine. See *Phase A as built* at the end.
**Fits:** enterprise plan M11 step 6 ("payslips, F11 template"), F11 (letterhead, logo, signatory per legal
entity), F14 (branding), and the agreed rule *payslips only come from an approved pay run*.

## What exists today, and what does not

| Exists (verified in code) | Missing |
|---|---|
| `pay_components` with `payslip_order`, kinds EARNING / DEDUCTION / EMPLOYER_CONTRIBUTION / REIMBURSEMENT / INFO | **The pay run engine (P2).** There is no `pay_runs` table yet, so there are no numbers to put on a payslip |
| Salary structures (versioned with `supersedes_id`), encrypted `annual_ctc` | Company address, CIN, PAN, TAN, GSTIN, PF / ESIC codes. `legal_entities` has only name, short name, country, financial-year month |
| KYC record with encrypted PAN, UAN, PF no., ESI no., bank account | Logo, colours, signatory, footer: no branding anywhere |
| `core/document_store.py`: encrypted local or S3 file storage | A PDF library (no WeasyPrint / ReportLab). Jinja2 is already in the lock file |
| Roles `PAYROLL_ADMIN` / `APPROVER` / `REVIEWER`; HR has `org.write` | |
| Web CSP allows `frame-src blob:` and `img-src data: blob:`, so a PDF preview and a logo preview can be shown | |

So the payslip **setup** (branding, company details, template, preview) can be built now. **Real payslips**
need the pay run engine first.

## The five rules that make it enterprise-grade

1. **A payslip is a frozen document, not a live page.** When it is generated, the numbers, the employee
   details, the branding and the template version are copied into it, and the PDF is stored with its
   SHA-256 hash. If HR changes the logo in December, the October payslip still looks exactly as it was
   issued, and downloading it again gives the same bytes.
2. **Numbers are never calculated while rendering.** The renderer only formats what the locked pay run
   holds. One wrong payslip loses trust (review PY-1), so the maths stays in the tested calculator.
3. **Set once for the group, override per company.** Every setting is inherited, field by field. The
   group sets the colour and footer once; each company overrides only what differs (its logo, its
   address, its signatory). The screen shows where each value comes from.
4. **Curated layouts, not a free-form designer.** HR picks one of a few professional layouts and switches
   sections and fields on or off. No one types HTML or CSS. Every payslip stays professional, and there is
   no template-injection risk.
5. **A correction never edits a published payslip.** It goes into the next run as arrears or recovery, or
   an off-cycle run. A cosmetic fix (a wrong designation) is a **reissue**: revision 2 marked "Revised",
   revision 1 kept, the reason recorded.

## Who sets what, and where

| What | Where in the app | Permission | Levels |
|---|---|---|---|
| **Company details**: registered name and address, CIN, PAN, TAN, GSTIN, PF establishment code, ESIC employer code, PT registration per state | Organization → Companies → a company → *Company details* | `org.write` (HR, Admin) | Per company only (it is legal data) |
| **Branding**: logo (normal, and an optional one for dark backgrounds), brand colour, accent colour, document footer, contact email, phone, website | Organization → *Branding* | `org.write` (HR, Admin) | Group default → company override |
| **Signatories**: name, designation, signature image, company | Organization → Branding → *Signatories* | `org.write`; every change is logged | Per company |
| **Payslip template**: layout, sections, employee fields, masking, signature mode, notes, PDF password | Payroll → Settings → *Payslip template* | `payroll.write` or `org.write` | Group default → company override |

Company details are not branding: the same values feed the PF ECR, ESIC file, Form 16 and bank files
later, so they belong to the company record.

### How a value is resolved

```
value for a payslip = the company's own value, if it has one
                      otherwise the group default
                      otherwise the built-in default (e.g. teal, "Modern" layout)
```

The same "most specific wins" rule as holiday calendars. The API returns each resolved value with its
source (`COMPANY`, `GROUP`, `DEFAULT`), so the screen can show *Inherited from Suraj Group · Override*.

A branch or location level is not included. A payslip carries the employer's registered office; the
employee's work location is shown as an employee field. Branch-specific values (an ESIC sub-code, a PT
registration in another state) live in the company details, keyed by state or location.

## What is on the payslip

Each block can be switched off unless marked *always*.

| Block | Contents |
|---|---|
| **Header** (*always*) | Logo, registered company name, registered address, CIN; title "Payslip for October 2026"; payslip reference |
| **Employee** | Name, employee number, designation, department, location, grade, date of joining, PAN, UAN, PF no., ESIC IP no., bank and account, tax regime. HR picks the fields and their order |
| **Pay period** (*always*) | Period, pay date, days in month, paid days, LOP days |
| **Earnings** (*always*) | Component, monthly rate, earned this month, arrears. Optional YTD column |
| **Deductions** (*always*) | PF, ESIC, PT, LWF, TDS, loan EMI, advance recovery, other |
| **Net pay** (*always*) | Large figure, amount in words in the Indian system ("Rupees Forty-Two Thousand Three Hundred Fifty Only") |
| **Employer contributions** | PF employer, ESIC employer, gratuity, labelled *not part of net pay*. Off by default |
| **Reimbursements** | Separate from earnings, not taxable |
| **Attendance summary** | Working days, present, holidays, weekly offs, leave, LOP, OT hours |
| **Leave balances** | Opening, availed, closing per leave type |
| **Tax summary** | Taxable income YTD, TDS YTD, projected annual tax (after the TDS calculator exists) |
| **Footer** (*always*) | Signature image + name + designation, **or** "This is a computer-generated payslip and needs no signature"; company footer text; generated date and time; page *x* of *y* |

Formatting rules: Indian digit grouping (1,23,456.00) and ₹; dates as 31 Oct 2026; **component labels and
order come from `pay_components`** (`name`, `payslip_order`); *hide lines that are zero* is an option.
Identifiers are **masked** by default (`XXXXXX1234` for a bank account, `ABCXX1234X` for PAN), the same
masked snapshot already agreed for `pay_run_employees`. An employee sees their own full identifiers in
My profile.

**Statutory form:** the wage-slip fields required by the labour codes and state rules differ by state. The
Payroll Reviewer (D-13) confirms the mandatory list once; the template then *locks* those fields on for
that company so they cannot be switched off.

### Layouts

| Layout | For | Look |
|---|---|---|
| **Modern** (default) | Office staff, on screen and PDF | Brand colour band at the top, earnings and deductions side by side, net pay in a highlighted panel |
| **Classic** | Accounts teams, auditors, banks | Bordered tables, traditional Indian payslip grid, black and grey only |
| **Compact** | Workers without email, bulk printing (PY-14) | Half A4 (two per sheet), essential blocks only, cut line between slips |

All layouts are A4, print in black and white without losing meaning, and use embedded fonts (Noto Sans,
which has ₹ and the Indian scripts for bilingual labels later). The brand colour is checked for contrast
against white (WCAG AA, 4.5:1); a colour that fails is darkened automatically for text and shown as a
warning.

## The flow

```
Pay run APPROVED (locked)
  └─ Generate payslips (payroll.write)        a background job, one row per employee
       ├─ resolve setup for the employee's company   (branding + template + signatory)
       ├─ build the payslip view model               (pure function, golden-tested)
       ├─ render HTML (Jinja2) → PDF (WeasyPrint)
       └─ store the PDF encrypted, with hash, template version and brand snapshot
  └─ Review: open any slip, see the exceptions (missing bank, missing PAN, negative net)
  └─ Publish (payroll.write), now or on a release date
       └─ employees are notified; the pay run becomes PUBLISHED
Employee → My payslips: month list → open (responsive HTML view) → Download PDF (the stored bytes)
HR → Payroll → a run → Payslips: download one, ZIP per company or department, print Compact two per page
```

Before publishing, payslips are visible only to payroll users. The daily provisional figures (D-14)
**never** produce a payslip; the setup preview uses a clearly watermarked *SAMPLE* slip.

### Setup preview

The template screen has the settings on the left and a **live preview** on the right. The preview is a
real PDF from the same renderer (`POST /v1/payroll/payslip-template/preview` returns the PDF; the page
shows it in a blob iframe, which the CSP already allows), so what HR sees is exactly what employees get.
It uses **sample data** by default, so HR without salary access can design it. Previewing with a real
employee's last payslip needs `payroll.read` for that employee.

## Data model (new tables, all tenant-scoped with RLS)

| Table | Key columns |
|---|---|
| `legal_entities` (new columns) | `registered_name`, address lines, `city`, `state_code`, `pincode`, `cin`, `pan`, `tan`, `gstin`, `pf_establishment_code`, `esic_employer_code` |
| `legal_entity_state_registrations` | `legal_entity_id`, `state_code`, `pt_registration_no`, `lwf_registration_no`, `esic_sub_code` |
| `brand_assets` | `kind` (LOGO, LOGO_DARK, SIGNATURE), `content_type`, `width`, `height`, `sha256`, `storage_ref` (`doc:`), uploaded by and at. **Immutable**, never deleted while a payslip uses it |
| `brand_profiles` | `legal_entity_id` (NULL = group default, unique per tenant + company), nullable fields meaning *inherit*: `logo_asset_id`, `logo_dark_asset_id`, `primary_color`, `accent_color`, `footer_text`, `contact_email`, `contact_phone`, `website`, `version` |
| `document_signatories` | `legal_entity_id`, `name`, `designation`, `signature_asset_id`, `status`. Shared with letters (F11) later |
| `payslip_templates` | `legal_entity_id` (NULL = group), `layout`, `sections` JSONB (on/off and order), `employee_fields` JSONB (field, order, mask mode), `options` JSONB (YTD, employer contributions, hide zero lines, signature mode, signatory, note, PDF password), `status` DRAFT / ACTIVE / RETIRED, `supersedes_id` (versioned like salary structures) |
| `payslip_documents` | `pay_run_employee_id`, `revision`, `reference`, `template_id`, `brand_snapshot` JSONB (every resolved value + asset ids), `storage_ref`, `sha256`, `status` GENERATED / PUBLISHED / SUPERSEDED / REVOKED, `generated_at`, `published_at`, `reissue_reason` |
| `payslip_access_log` | who, which payslip, VIEW / DOWNLOAD / BULK, when, IP. Plan rule: *payslip and salary views are logged* |

**Reference:** `<company short name>/<YYYY-MM>/<employee number>`, with `-R2` for a reissue. Unique by
construction, so no numbering series is needed.

## Security

- **Payslip PDFs are salary data.** They are sealed with the **payroll keys and pepper**
  (`PAYROLL_ENCRYPTION.md`), not the identifier keys, so someone holding only the KYC keys reads no salary.
  The document store needs a `purpose` argument for this. The payslip lines in `pay_run_employees` are
  sealed the same way.
- **Logo upload:** PNG, JPEG or WebP only, at most 1 MB, at least 200 px wide. Pillow decodes and
  **re-encodes** it, which drops metadata and anything hidden in the file. SVG is refused (it can reference
  external files).
- **Rendering cannot reach the network.** WeasyPrint's `url_fetcher` refuses every URL; logos and fonts are
  passed in as embedded data. Jinja2 autoescape is on; footer text and notes are plain text.
- **Signature images** can be misused for forgery: stored encrypted, only ever drawn into PDFs, the raw
  image shown only to `org.write` users, every change logged.
- **Access:** employees see only their own published payslips (`/v1/payroll/my-payslips`). HR and payroll
  go through `authorize_employment()` with `payroll.read`. Responses carry `Cache-Control: no-store`,
  `Content-Disposition: attachment` and `Content-Security-Policy: sandbox`, as KYC downloads do.
- **Optional PDF password** per company, from a pattern such as date of birth `DDMMYYYY` or PAN first five
  letters + birth year. Off by default for in-app download (the login already protects it); recommended
  once payslips are emailed.

## Operations

- **Dependencies:** `weasyprint` (adds Pango and HarfBuzz to the backend image, about 60 MB), and the Noto
  fonts committed under `backend/src/hrms/assets/fonts/` so every server renders identical PDFs.
- **Speed:** one A4 payslip takes roughly 0.1–0.3 s. 1,000 employees ≈ 2–5 minutes in the jobs runner
  with checkpoints; it can resume. Measure it in `backend/perf/` before go-live.
- **Storage:** about 40–80 KB per PDF; 1,000 employees × 12 months ≈ 1 GB a year. S3 in deployed
  environments.
- **Tests:** golden tests for the view model and amount-in-words; a PDF smoke test (renders, text extracts,
  hash stable); an RLS test that one company's HR cannot open another company's payslip; e2e for upload →
  preview → generate → publish → employee download.

## Build order

| Phase | Needs | Delivers |
|---|---|---|
| **A · Setup** | Nothing new | Company details, Branding (group + per company), logo upload, signatories, payslip template with live SAMPLE preview |
| **B · Payslips** | Pay run engine (P2) | Generate from an approved run, review, publish, My payslips page, HR download / ZIP / Compact print, access log |
| **C · Later** | TDS, email provider | Tax summary block, email delivery with password-protected PDF, reissue screen, bilingual labels (D-9), verification QR code |

## Decisions (2026-10-29)

The user chose the recommended defaults:

- group default plus a per-company override, with no branch level;
- no PDF password for in-app download;
- Modern as the default layout.

## Phase A as built

| Piece | Where |
|---|---|
| Migration 0075 | `legal_entities` company-detail columns; `brand_assets` (append-only), `brand_profiles`, `document_signatories`, `payslip_templates`. One row per scope via `UNIQUE … NULLS NOT DISTINCT (tenant_id, legal_entity_id)`; change history by trigger |
| Company details | `PATCH /v1/org/legal-entities/{id}` (group admin). Formats checked with plain messages (`org/schemas.py`); Organization → Companies → edit → *Details for payslips* |
| Branding API | `modules/branding/`: `/v1/branding/profiles`, `/resolved`, `/assets` (upload, image), `/signatories` |
| Template API | `payroll/payslip_templates.py`: `/v1/payroll/payslip-templates` overview, `PUT /group`, `PUT\|DELETE /companies/{id}`, `POST /preview?format=pdf\|png` |
| Renderer | `payroll/payslip/`: `formatting.py` (₹ grouping, words, masking), `document.py` (pure view model), `sample.py`, `issuer.py`, `render.py` + `templates/payslip.html.j2`; fonts in `hrms/assets/fonts` |
| Screens | Organization → **Branding** (group, companies, signatories, payslip layout); Payroll → **Payslip** (layout only, for payroll admins) |
| Tests | `tests/test_payslip_document.py` (pure, renders every layout to one page), `tests/test_payslip_branding.py` (HTTP, scopes) |

Where it differs from the design above:

- **Branding overrides field by field, but a template overrides as a whole.** A company either uses the
  group's layout or has its own complete one (*Customize for this company*). Mixing two layouts field by
  field would make the result hard to predict.
- **Templates are not versioned rows.** Each scope has one row; its change history comes from the
  database trigger. Reproducibility comes from Phase B: each generated payslip will copy the resolved
  template and branding into its own record, so a later edit never changes an issued payslip.
- **Per-state registrations** (PT, LWF, ESIC sub-codes) are left for the statutory files, which need
  them; the payslip prints CIN, TAN, PF and ESIC codes from the company.
- **The preview is an image.** `format=png` rasterizes the PDF with pypdfium2 (about 40 ms), because
  phone browsers don't display PDFs inline and the desktop PDF viewer flashes while loading. *Download
  sample PDF* fetches the real PDF.
- **No dark-background logo**, no PDF password and no locked statutory fields yet (Phase C).
- **Permissions:** branding and signatories need `org.write` (group-level for the group default and
  group-wide signatories). Templates accept `payroll.write` or `org.write`. Logos are visible to
  `org.read` and `payroll.write`; signature images only to `org.write`.
- **Deployment:** the backend image installs Pango and HarfBuzz (`backend/Dockerfile`), and so does CI.
  WeasyPrint is imported only when a PDF is rendered, so a server without Pango still starts.

# 3 · Industry coverage: how one product fits a factory, a forwarder and an IT firm

**The rule:** industries differ in **configuration and packs, never in code branches**. If an industry needs something the foundations cannot express, the foundation is extended for every tenant. No customer-specific `if` statements are allowed (architecture risk R3, "anchor-tenant capture").

## How industry differences are absorbed

| Difference between industries | Absorbed by |
|---|---|
| Names ("Plant", "Store", "Site", "Section", "Associate") | Terminology (F14) |
| Worker categories (permanent, probationer, trainee, apprentice, contract worker, fixed-term, casual / daily wage, consultant, intern, part-time) | Employee types lookup with attributes (F2), applicability conditions (F4) |
| Working hours, weekly offs, overtime rules | Per-entity duration rules (punch any time, total time counted), weekly-off patterns, OT policy (M6, F5). **No shifts by decision D-15.** |
| Leave rules and statutory leave | Leave policy sets, accrual bases, pack templates (M7) |
| Required documents and licences | Document types and the required-documents matrix (F10) |
| Mandatory training and recertification | Training requirements matrix (M9) |
| Approval chains | Workflow resolvers and conditions (F6) |
| Compliance obligations | Country pack and establishment registrations (M14, M1) |
| Capture method (biometric, geo, kiosk, web) | Capture settings per location (M6, F18, F19) |
| Extra data per industry | Custom fields and forms (F3) |
| Modules not needed | Module switches per entity (F18) |

---

## Manufacturing and factories

Paramount Propack, and probably RABS Industries (confirm), are factories in the Suraj Group set-up.

| Need | How the plan covers it | Where |
|---|---|---|
| Round-the-clock work: people come at different times, including nights | No shifts (D-15): punch any time; the day belongs to the first IN; total time counted; 24 h window, then missed punch; optional night-band hours | M6 |
| Staggered weekly off (not Sunday), compensatory holiday when the weekly off is worked | Per-employee weekly-off day (a calendar setting, not a shift), off-day work rule, comp-off | M6, M7 |
| Overtime: daily, weekly and quarterly caps; double rate; register | OT policy caps and multiplier; OT register report in the pack | M6 |
| Earned leave by days worked (1 per N days, eligibility after N days) | Accrual basis "per N days worked" with a threshold | M7 |
| Biometric / face devices at several gates; contract workers on the same devices | Device registry and adapters; contract workers as employees with a contractor link | F19, M21 |
| Workers without email or smartphones | Employee code + OTP, kiosk mode, regional language, printed letters | M20, F14 |
| Going out during the day (gate pass) | Checking out and back in deducts the away time automatically; an hours permission (N hours a month) where the entity allows it | M6 |
| Late-coming penalties ("3 lates = ½ day") | Penalty rules in the policy | M6 |
| Contract labour compliance (licence, headcount limit, contractor PF/ESIC proof) | Contractor master and monthly verification | M21, M14 |
| Factory licence and other registration renewals | Establishment registrations with expiry obligations | M1, F7 |
| Safety training, medical fitness, recertification | Mandatory training matrix with validity; fitness certificate as a document type with expiry | M9, F10 |
| PPE and uniform issue | Consumable asset types issued without return | M12 |
| Standing orders, show-cause, enquiry | Disciplinary cases | M22 |
| Statutory registers (state forms: adult workers, OT, leave with wages, …) | Pack reports with state form layouts, generated from data. **Formats must be verified per state.** | M18, F16 |
| Apprentices and trainees | Employee types with their own leave, attendance and training policies (and a stipend structure in payroll) | F2, F5, M11 |
| Wages: minimum wage by state, skill category and zone; OT at a statutory multiple; night allowance (from night-band hours); attendance and production incentives | Payroll inside the HRMS: minimum-wage table and pre-lock check; attendance-driven components (per OT hour × rate, per shift day); input-driven incentive lines | M11 |
| Piece-rate or production-linked pay | Input-driven component (quantity uploaded per period × rate table), checked against the minimum wage | M11 |
| Women's night-shift conditions (state-specific consent and safety rules) | A night-band alert (if the entity turns on night hours) plus a consent document type. **Rules vary by state, so verify before enabling.** | M6, F10 |

**Factory pack contents.**

- Terminology (Plant, Section, Supervisor, Worker)
- Employee types (Worker, Staff, Apprentice, Trainee, Contract worker)
- Attendance rule templates: full-day and half-day hours, OT threshold, weekly offs
- OT policy template
- Earned-leave-by-days-worked template
- Document types (fitness certificate, Form 11, nomination)
- Training programmes (safety induction, fire drill)
- Asset types (PPE, uniform)
- Obligations (factory licence, annual / half-yearly returns)
- Dashboard layout (present now, worked hours, OT hours, contract headcount)

---

## Logistics, freight forwarding, shipping agencies, container carriers

Suraj Forwarders, Suraj Forwarders & Shipping Agencies, SR Container Carriers and EXIMBIZ fall here.

| Need | How covered | Where |
|---|---|---|
| Staff at ports, CFS, ICDs and client sites, not at an office | Several geo-fences per location; on-duty (OD) requests with purpose; mobile punch | M6 |
| 24 × 7 operations desks, vessel-driven overtime | Punch any time with total time counted; OT with a pre-approval switch | M6 |
| Drivers: licence, hazardous-goods endorsements, medical fitness | Document types with expiry and reminders; assets (vehicles) with insurance expiry | F10, M12 |
| Field staff on the move with company phones and SIMs | Asset types for SIM and phone; clearance at exit | M12, M13 |
| Frequent inter-company transfers within the group | Inter-company transfer as linked employments; group-unique employee ID option | M2, F12 |
| Customs and port passes per person | Document type "Port / customs pass" with expiry | F10 |
| Travel for clients | OD now; travel and expenses later (expansion) | M6, [04](04-delivery-roadmap.md) |

**Logistics pack contents.** Terminology (Branch, Desk), employee types (incl. drivers, field executives), document types (driving licence, port pass), OD purposes, a vehicle asset type.

---

## IT, consulting and IoT

Novusha Consulting and Alluvium IoT fall here.

| Need | How covered | Where |
|---|---|---|
| Hybrid / WFH, flexible hours | WFH requests and eligibility; flexi policy (minimum hours, no fixed start) | M6 |
| Client-site work | OD, or a location of type "Client site" | M6, M1 |
| Certifications with expiry | Document type plus training records | F10, M9 |
| Projects and allocation | A custom dimension "Project" on assignments now; timesheets later | F3, [04](04-delivery-roadmap.md) |
| Laptops, licences, access | Asset types; the IT clearance owner | M12, M13 |
| SSO with Google or Microsoft | OIDC per tenant | F19 |

---

## Trading and distribution

Sansar Tradelink falls here: an office plus a small field sales team. It is covered by the base pack with OD for field sales and a small-company set-up (below).

---

## Industries outside the Suraj Group, checked so the platform can be sold to them

| Industry | Distinct needs | Covered by | Gap or later |
|---|---|---|---|
| **Hospitals and healthcare** | 24×7 rosters, on-call, split shifts; nursing and medical council registrations with expiry; mandatory infection-control training; overtime caps | Punch any time (a split day is just several sessions), document expiry, training matrix, on-call allowance as an input-driven pay component (M11) | Duty planning (who *should* be on duty) is not covered: no rosters (D-15) |
| **Retail chains** | Many small stores, store managers as approvers, part-time and hourly staff, seasonal bulk hiring, high attrition | Location-scoped roles, part-time employee type with FTE, bulk hiring mode, bulk exit | Hour-based scheduling against footfall: later (WFM) |
| **Construction and projects** | Temporary sites, daily-wage workers via contractors, site transfers, BOCW welfare registration | Locations of type Site with start/end, geo-fence punch, contractors (M21), establishment registrations | Labour camp management: later, as a custom object |
| **Hospitality** | Split shifts, service charge, uniforms, food-handler certificates | Punch any time (split days as several sessions), consumable assets, document expiry, service charge as an input-driven pay component (M11) | Points-based service-charge distribution formulas: later |
| **Education** | Academic year, vacation leave, faculty qualifications | Leave year setting, vacation leave type, qualifications section | — |
| **BFSI** | Strict access and audit, mandatory compliance training, background verification | Data classes, access review, training matrix, BGV as an onboarding item | BGV vendor integration later |
| **Security services** | Guards at client sites, police verification, uniforms | Client-site locations, document type with expiry, consumables | Billing to clients: out of scope |

---

## Organisation size

| Size | What they need | How the plan serves them |
|---|---|---|
| **10–50 people** (startup, trading office) | Working in a day, few settings | Setup wizard with a pack (F16); defaults that just work; unused modules switched off; one HR role doing everything |
| **200–2,000** (most Suraj companies, typical factories) | Delegated HR per company and location, round-the-clock work, proper approvals | Entity-scoped roles and rules, resolvers by manager and HOD, period close |
| **10,000–200,000** (large groups) | Delegated admin per company, SSO, API, heavy reports | Entity-scoped administration, entity groups, configuration bundles, API and webhooks; scale limits in [04](04-delivery-roadmap.md) and architecture 07 |

---

## Other countries (later)

The design keeps India-specific items in the **country pack**:

- identifiers (UAN, ESIC IP, PAN, Aadhaar) live in the statutory profile and identifier registry, not as core columns
- states are data
- the financial year is configurable per entity
- currency is stored on every money field

Selling outside India still needs a residency decision (architecture D4 / R18) and a country pack per country.

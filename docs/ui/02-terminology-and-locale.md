# UI 2 · Terminology, language and locale

## Terminology: never hard-code organisation nouns

The same concept has different names in different industries. Screens ask `HRMS.terms(pack, tenantOverrides)` for the noun instead of writing it.

| Key | Platform default | Group company (SURAJ) | Manufacturing | Retail | Healthcare | IT services |
|---|---|---|---|---|---|---|
| `legalEntity` | Company | Company | Company | Company | Company | Company |
| `location` | Location | Branch | Plant | Store | Facility | Office |
| `orgUnit` | Department | Department | Department | Function | Department | Practice |
| `team` | Team | Team | Line | Team | Unit | Delivery team |
| `worker` | Employee | Employee | Employee | Associate | Employee | Employee |
| `workerId` | Employee ID | Employee ID | Employee ID | Associate ID | Employee ID | Employee ID |
| `unitHead` | Head of department | HOD | HOD | Head of department | Head of department | Head of department |

Rules:

- Filter labels, table headers, form labels, report column names and notification templates all go through terminology.
- Module names (§38) and statuses (§4) are **not** terminology. They stay fixed so training material, support and documentation match across tenants.
- A tenant can override any key; industry packs set the defaults.

## Language

- Every UI string lives in a message catalogue (ICU MessageFormat, so plurals and gender-neutral phrasing work); no string is concatenated in code.
- English at launch. Self-service in regional languages next: the `sans` family (Noto Sans, then Noto Sans Devanagari and Gujarati) already covers Hindi, Marathi and Gujarati; add the matching Noto family for each further script.
- Tenant-authored content (leave type names, policy documents, checklist items, notification templates) is stored per language, falling back to the tenant's default language.
- Layout uses logical CSS properties (`margin-inline-start`, `padding-inline`), so right-to-left scripts can be added for future regions without rework.

## Locale formatting

| Value | Rule | Example (en-IN) |
|---|---|---|
| Counts | `HRMS.formatCount(n, locale)`; Indian digit grouping for en-IN | 1,24,860 |
| Money | `HRMS.formatMoney(n, currency, locale)`; currency comes from the legal entity; no decimals in summaries | ₹12,50,000 |
| Business dates (joining date, leave days, effective dates, attendance date) | Calendar dates with no time zone; `HRMS.formatDate` | 21 Sept 2026 |
| Instants (punch time, approval time, audit entries) | Stored in UTC; shown in the location's time zone, with the zone named when it differs from the viewer's | 09:12 IST |
| Week start, weekend, fiscal year, leave year | From tenant and location configuration, never assumed | April–March for many Indian tenants |

The ICU data in current browsers prints the short month for September as "Sept" in en-IN. Accept whatever `Intl` returns rather than patching it.

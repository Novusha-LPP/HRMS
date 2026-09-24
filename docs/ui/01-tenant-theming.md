# UI 1 · Tenant theming and white-label

One product serves every tenant. A tenant can make it recognisably theirs, but cannot make it harder to read or change what a status means.

## What a tenant can set

| Setting | Where it shows | Guard |
|---|---|---|
| Brand colour (one) | Primary button, logo tile, selected navigation item, links | `HRMS.deriveBrand()` computes `on-brand`, `brand-ink`, `brand-soft` and `brand-edge` so every pair meets WCAG AA. A colour that cannot carry a label at 4.5:1 is darkened, and the admin screen shows the adjusted value before saving. |
| Logo | `.hr-nav__logo` (32px tile), login page, letters, email header | Square SVG or PNG of at least 64px on a transparent background; the tenant's initials on `brand` when absent |
| Display name | Navigation, page titles in the browser tab, emails | Up to 40 characters; truncated with a tooltip in the navigation |
| Custom domain | `hr.tenant.com` instead of `tenant.hrms.app` | TLS issued automatically; the host must resolve to exactly one tenant |
| Email sender | "Kaveri HR <hr@kaveri.example>" | SPF, DKIM and DMARC verified before use; the platform sender until then |
| Terminology | Organisation nouns everywhere (UI 2) | From a fixed list of keys; no free-form relabelling of statuses |
| Languages and locale | UI strings, dates, numbers, currency | Only languages the platform ships; tenant-authored content translated by the tenant |
| Default density | Table row height | `row-height` or `row-height-compact` |

## What a tenant cannot change

- **Status colours and wording categories.** "Overdue" is `danger` in every tenant. Brand colours never appear in status badges.
- **Neutrals and layout:** `surface`, `surface-raised`, `ink`, the `nav-bg` navigation and the light workspace, the 16:9 frame (§38).
- **Type, spacing, radii and shadows.**
- **The focus ring** (`focus`), which is tuned to reach 3:1 on every surface, including `nav-bg`.

## How it is applied

1. The tenant configuration endpoint returns the brand colour, logo URL, terminology and locale with the session.
2. The app calls `HRMS.applyTenantBrand(document.documentElement, brand)` once at start-up. Only the five brand custom properties change; no stylesheet is rebuilt per tenant.
3. Emails, PDFs and letters use the same derived values, computed server-side from the same algorithm.

The **Tenant brand (example)** theme in this system shows the result for a pale gold brand (`#e0a21b`): the primary button keeps dark `on-brand` text, and links and the selected navigation item use the darker `brand-ink` (`#8b6411`). Switch between the two themes to see everything the tenant cannot change stay put.

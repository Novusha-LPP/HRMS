# Ember Sand theme

**Step 1 — Study what exists**

The application has one theme architecture, with independent choices for colour palette,
light/dark/system mode, and dashboard layout. Adding a palette does not require new
components or a folder restructure.

| Concern | Existing implementation |
|---|---|
| Palette registry and types | `frontend/src/context/ThemeContext.tsx`: `ColorTheme`, `COLOR_THEMES` |
| Design tokens | `frontend/src/index.css`: RGB channels, allowing Tailwind opacity utilities |
| Token-to-utility mapping | `frontend/tailwind.config.js`: brand 50–950, surfaces, foregrounds, borders, semantic colours |
| Palette loading | `<html data-color-theme="…">` |
| Mode switching | `.dark` on `<html>`; system mode listens to `prefers-color-scheme` changes |
| Browser persistence | `hrms_color_theme` and `hrms_theme` in local storage |
| Account persistence | `frontend/src/lib/preferences.ts`, `GET/PATCH /v1/me/preferences` |
| Selectors | Registry-driven `AppearanceControls`; palette shortcut in `AppShell` |
| Icons | `frontend/src/components/icons/ThemeIcons.tsx` |
| Charts | `chartPalette.ts` exposes CSS variables with original-colour fallbacks; `Charts.tsx` has Midnight-specific rendering |
| Backend validation | `backend/src/hrms/modules/preferences/schemas.py` |
| Database validation | `ck_user_preferences_theme`, previously limited to two IDs by migration 0028 |

Both themes share Inter body typography, spacing, responsive layout, the component library,
and token names. The dashboard's Widgets/Overview preference is independent of the palette.
Tenant users save their palette to their account; platform/public appearance controls save
it locally. The legacy stored ID `hrms-dashboard` still resolves to Midnight Blue.

| Detail | Classic Teal | Midnight Blue |
|---|---|---|
| Light primary button | Teal `#0F766E` | Royal blue `#1D68E8` |
| Light canvas | Zinc `#F4F4F5` | Cool blue-white `#F4F7FC` |
| Dark canvas | Near-black zinc `#09090B` | Navy `#0B1120` |
| Sidebar | Follows neutral mode | Navy gradient in both modes |
| Icons | Standard Lucide outlines | Custom glyphs, including filled KPI silhouettes |
| Charts | Generic ring/bar treatment | Additional gradients and column/progress treatments |

The exact addition procedure is: add a kebab-case ID to the union/registry/storage
validation; add scoped light and dark CSS tokens and component rules; extend the icon
dispatcher if necessary; ensure the shortcut traverses the registry; extend the API
Literal and OpenAPI enum; add an Alembic migration expanding the existing check constraint;
verify browser restoration, account persistence, mode switching, and old palettes.

**Step 2 — Decide the direction**

Ember Sand is warm, calm, and editorial. Its audience is HR staff and managers spending
long sessions reading tables and reviewing people-related requests. Terracotta actions,
sand backgrounds, moss links, and plum details give it a distinct identity. Dark mode uses
warm charcoal and peach actions rather than a cool navy foundation.

Serif headings, compact corners, flatter surfaces, and an inset navigation marker reinforce
that identity beyond the palette. Shared navigation, information hierarchy, and responsive
behaviour remain familiar. All new visual rules are scoped to `ember-sand`.

**Step 3 — Choose the colours**

| Role | Light | Dark | Purpose |
|---|---|---|---|
| Primary | `#AD4225` | `#FDA48A` | Warm, recognisable actions |
| Primary hover | `#963A21` | `#FDBDA8` | Visible interaction feedback |
| Primary foreground | `#FFFFFF` | `#2B241E` | Readable button labels |
| Secondary / plum | `#735071` | `#D4ADCE` | Supporting icon and chart detail |
| Accent / moss | `#53652D` | `#C3D391` | Links and quiet emphasis |
| Background | `#F5F0E8` | `#1C1917` | Warm page foundation |
| Panel | `#FAF7F2` | `#231F1C` | Main workspace |
| Surface | `#FFFFFF` | `#2C2622` | Cards and controls |
| Muted surface | `#EDE5DB` | `#39302A` | Tables, sidebar, subtle grouping |
| Text | `#2B241E` | `#FAF3E8` | Headings and primary content |
| Secondary text | `#625447` | `#D1C1B1` | Supporting content |
| Subtle text | `#70604F` | `#B5A18E` | Hints and secondary labels |
| Divider border | `#DDD2C6` | `#51443A` | Decorative separation |
| Control border | `#9B897B` | `#927D6B` | Visible input/control boundaries |
| Success | `#38633E` | `#A3CEA6` | Positive status |
| Warning | `#8A550F` | `#E8BD74` | Attention required |
| Error | `#B33342` | `#FF9DA6` | Failure/destructive status |
| Information | `#345F8A` | `#9DBEE5` | Informational status |

Contrast was calculated using sRGB relative luminance. All reported ratios are rounded
for display; pass/fail checks use unrounded values.

| Tested pair | Light | Dark |
|---|---|---|
| Main text / background | 13.47:1 | 15.86:1 |
| Subtle text / worst of the four neutral surfaces | 4.84:1 | 5.19:1 |
| Semantic text / worst neutral surface | 4.85:1 | 6.52:1 |
| Primary button label / fill | 5.86:1 | 7.90:1 |
| Primary button label / hover fill | 7.18:1 | 9.48:1 |
| Control border / surface | 3.36:1 | 3.81:1 |

The target is at least 4.5:1 for ordinary text, including button labels, and 3:1 for
meaningful control boundaries and icons, following
[WCAG text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
and [non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).
Subtle divider borders are decorative and are separate from the stronger control border.
Semantic badges keep their text labels, so status is not conveyed by colour alone.

**Step 4 — Choose icons and other assets**

- Installed Lucide outline glyphs, with 1.75px strokes and rounded caps/joins. Theme-aware
  icons expose `data-icon-set="ember-sand"`; direct Lucide imports receive the same scoped
  stroke treatment.
- KPI icons retain their semantic colours in lightly tinted, bordered 6px containers.
  Their glyphs stay compact rather than using the larger Midnight silhouettes.
- Inter remains the body/control/table font. Georgia, with local serif fallbacks, is used
  for 28px page headings and 17px card titles. No additional font downloads are introduced.
- Cards, buttons, and inputs have 6px corners; popovers have 10px corners. Cards have a
  restrained 2px bottom shadow. The workspace is flat and the sidebar tonal.
- Brand marks use a solid fill. Charts use the existing accessible labels and semantic
  palette variables. Existing chart structure and subtle area fills remain shared.
- Avatar initials use the main foreground over their personalised tints. The company
  sign-in panel uses warm charcoal and readable cream supporting text without glows.
- Focus uses a solid 2px primary outline. Select chevrons have separate light/dark SVG
  colours for readability.

**Step 5 — Build it**

Implementation files:

- `frontend/src/context/ThemeContext.tsx`: registry, type, stored-value restoration.
- `frontend/src/index.css`: complete palette overrides and scoped visual treatments.
- `frontend/src/components/icons/ThemeIcons.tsx`: Ember icon dispatcher.
- `frontend/src/components/layout/AppShell.tsx`: inert styling hooks and registry cycling.
- `frontend/src/components/ui/Avatar.tsx`, `frontend/src/pages/LoginPage.tsx`: inert hooks
  for Ember-only initials and sign-in-panel treatments.
- `frontend/index.html`: restores Ember Sand before React paints.
- `backend/src/hrms/modules/preferences/schemas.py`: third API enum value.
- `backend/alembic/versions/0049_ember_sand_theme.py`: expands the check constraint without
  changing existing rows/defaults; downgrade converts only Ember Sand rows to Classic Teal.
- `backend/openapi.json`: updated preference enums.
- `backend/tests/test_preferences.py`, `backend/tests/test_preferences_schema.py`: account
  roundtrip/independence and schema validation.
- `frontend/e2e/themes.spec.ts`, `frontend/playwright.themes.config.ts`: isolated browser
  checks with synthetic API fixtures; `npm run test:themes` runs this suite.

Run the normal deployment migration process before releasing this frontend/backend:
the database must reach revision 0049 to save the new palette. Choose Ember Sand from the
account menu's Colour theme selector or cycle to it using the top-bar palette button.
Light, Dark, and System continue to work independently of the palette choice.

**Step 6 — Verify**

- [x] Production TypeScript/Vite build passed.
- [x] Frontend lint passed with 14 existing warnings; new browser tests/config lint cleanly.
- [x] All 8 existing frontend test files passed.
- [x] All 14 fixture-backed Chromium tests passed against the final production build.
- [x] Both modes checked on Widgets dashboard and all 14 Overview cards, employees and
  the employee form, attendance calendar/list, leave and request details, profile,
  company sign-in, and platform sign-in.
- [x] Desktop (1440 × 1000), phone (390 × 844), expanded/collapsed sidebar, mobile
  navigation, and phone forms checked without page overflow or clipped controls.
- [x] Dropdown registration, three-theme shortcut cycling, browser reload, account
  preference updates, and live system-mode changes verified.
- [x] Classic Teal and Midnight Blue baselines retained their tokens, geometry,
  typography, icons, and sidebar treatments in light/dark mode.
- [x] Thirty rendered states checked with translucent backgrounds composited before
  contrast calculation: 1,980 text samples and 454 navigation/action icon samples,
  zero failures. The lowest ordinary-text ratio was 4.509690813:1; the lowest audited
  icon ratio was 4.843604116:1. Pass/fail used unrounded values.
- [x] Primary-button hover, enabled form buttons, status badges, 2px keyboard focus
  outlines, and focused-input borders passed their contrast checks in both modes.
- [x] Success-button and policy-switch variants checked using isolated probes with the
  actual component CSS classes; switch thumbs exceeded 3:1 contrast.
- [x] All 26 targeted backend tests passed against a disposable PostgreSQL 18 database.
  A fresh database migrated through 0049; populated downgrade/re-upgrade across three
  independent tenants preserved existing palettes, dashboard choices, defaults, and
  forced row security. Unknown theme IDs remained rejected. The temporary cluster
  was stopped, and no shared database was accessed.
- [x] Whitespace/diff checks passed.

Verification corrected several shared combinations only for Ember Sand: avatar initials,
the action-centre notification count, light overview counters, dark success-button labels,
checked policy-switch thumbs, and company sign-in supporting text. Overview legend dots
were aligned with the donut's theme colours.

Assumptions and review:

- The colour theme applies throughout the application. Dashboard layout is an independent
  preference and has not been coupled to this theme.
- Existing fonts and installed vector icons are sufficient. Review the Georgia headings
  and warm palette for brand fit; body text, controls, and tabular values remain Inter.
- Browser checks use synthetic populated data and intercept API requests. Actual account
  persistence and database constraints were tested separately against the disposable DB.
- Chromium desktop/mobile emulation was verified; Safari, Firefox, and physical devices
  were not tested. Contrast results cover the rendered states listed above, rather than
  constituting a full application accessibility certification.
- Apply migration 0049 through the normal deployment process before enabling account
  saves in the released application. No live deployment or shared-database migration was
  performed during this work.

Run the browser checks with `cd frontend && npm run test:themes`. The standalone config
builds/starts a local preview automatically and requires no backend or database. Set
`HRMS_THEME_BASE_URL` to use an existing preview. The review run saved 38 screenshots,
30 contrast reports, and `verification.json` under `/tmp/hrms-theme-review`.

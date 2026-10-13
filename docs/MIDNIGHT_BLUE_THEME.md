# Midnight Blue — Midnight Orbit refresh

Midnight Blue now has a luminous, geometric identity. The theme name and stored ID stay
the same, and the design works in light, dark, and system modes.

The navy foundation remains familiar. Cyan orbital lines, blue-to-violet navigation,
floating cards, and larger KPI values make the theme feel distinct from Classic Teal
and Ember Sand. No fonts, image assets, or dependencies were added.

## Visual direction

- Page headers become navy feature panels with concentric orbital lines. The artwork is
  drawn in CSS backgrounds, so it cannot intercept clicks or clip action popovers.
- Sidebar illumination uses restrained cyan and violet radial gradients. Active links
  have a cyan inset marker and a blue-to-violet fill.
- Cards use 18px corners, the main workspace 24px corners, headers 22px corners, and
  controls 11px corners. Phone headers use 18px corners and 20px padding.
- KPI cards use subtle corner rings, uppercase labels, larger tabular values, and 38px
  icon containers. Existing custom Midnight icons remain in place.
- Tables use quiet blue-grey headers and clear status colours. Sidebar section,
  table-header, and KPI labels have been enlarged for readability. Quick actions
  lift 2px on pointer hover when motion is enabled.
- Inter remains the typeface. Header titles use 26px bold type with tighter spacing,
  rather than Ember Sand's serif treatment.

## Palette

| Role | Light | Dark |
|---|---|---|
| Primary action | `#245CE6` | `#98B8FF` |
| Primary hover | `#1E4ECA` | `#BDD1FF` |
| Primary foreground | `#FFFFFF` | `#0B1426` |
| Cyan accent | `#086D83` | `#9FDDEC` |
| Violet | `#6741BE` | `#BFAAFF` |
| Canvas | `#EDF2FB` | `#081224` |
| Panel | `#F5F8FE` | `#0D1930` |
| Surface | `#FFFFFF` | `#15233E` |
| Muted surface | `#E9EFF9` | `#1D3050` |
| Text | `#172942` | `#F0F6FF` |
| Supporting text | `#435573` | `#C8D7F1` |
| Subtle text | `#526582` | `#A3B7D8` |
| Border | `#D7E2F3` | `#2A4167` |
| Control border | `#7285A4` | `#748FB5` |
| Success | `#167144` | `#79DCAF` |
| Warning | `#8B570A` | `#F8CE82` |
| Error | `#B82D4B` | `#FF9AAD` |
| Information | `#225FD2` | `#97BAFF` |

Primary button labels have 5.60:1 contrast in light mode and 9.31:1 in dark mode.
Neutral-surface text and semantic text were checked before implementation, including
10% status tints. Decorative cyan glows are separate from text colours.

## Implementation

The refresh is scoped to `[data-color-theme="midnight-blue"]` in
`frontend/src/index.css`. Shared components gained inert class hooks in
`PageHeader.tsx`, `StatCard.tsx`, and `AppShell.tsx`; these hooks do not style other
palettes. The registry description was updated. One decorative white dot was removed
from the filled Midnight Users glyph because it disappeared on white active icons.

Existing light semantic colours were too bright for ordinary text, and the previous dark
primary-button hover used white text on a bright blue fill. The new palette corrects
these combinations. Sidebar account avatars, status counters, dark success buttons,
checked switch thumbs, and sign-in supporting text also receive scoped contrast fixes.
Overview legend dots match their donut segments.

Header ghost actions and icons use a readable foreground. Date controls on a
surface-coloured tile use the primary focus outline; controls on navy use an icy blue
outline. Nested action groups wrap on phones.

## Usability optimization

- The top bar uses an opaque surface without an unnecessary backdrop blur. The
  navy, cyan/violet detail, original color tokens, and card geometry stay intact.
- At widths up to 380px, feature-panel padding reduces to 16px, gaps to 12px, and
  headings to 22px. Mobile navigation targets are at least 44px tall. Sidebar
  keyboard focus uses the icy outline so it stays visible on an active link.
- The application shell uses dynamic viewport height. Mobile navigation now has
  a dialog label, contained focus, Escape handling, focus restoration, and scroll
  locking. Resizing to desktop closes the mobile drawer and releases its lock.
- Reduced motion disables Midnight animations and transitions, loading shimmer,
  quick-action lift, and pressed-button scaling. Normal hover effects run only
  for a fine pointer and do not override pressed or disabled states.
- Shared dialogs and sheets contain keyboard focus in the top modal, restore the
  opener when closing, and keep background scroll locked until the final modal
  closes. Inline menus receive Escape before their containing modal; inline
  editing handles its own cancellation. Confirmation titles/descriptions and
  command search have accessible dialog names.
- Command search and other dialogs are bounded to the available viewport and
  scroll long content on short screens. Modal forms retain their existing React
  autofocus behavior while restoring the original opening control.

These changes add no package, font, image asset, database change, or animation
library. Shared keyboard fixes also apply to Classic Teal and Ember Sand; their
palette styling stays separate.

No backend or database change is needed: the existing `midnight-blue` preference remains
valid, and dashboard layout is still independent of the palette.

## Initial refresh verification

- Production build passed. Frontend unit tests passed across eight test files. Lint
  passed with the same 14 existing warnings; `git diff --check` passed.
- All 28 Chromium theme checks passed. These cover Midnight Blue light/dark/system and
  persistence, Classic Teal baselines, and Ember Sand regressions.
- Reviewed desktop and phone dashboards, all 14 overview cards, employee tables and
  forms, attendance calendar/list, leave details, profile, company/platform sign-in,
  expanded/collapsed navigation, and appearance settings.
- Additional checks cover Daily Analysis date focus and the Today hover action, Policy
  Info hover, inactive weekday labels, phone Attendance action wrapping, primary-button
  hover, semantic success buttons, and checked switch thumbs.
- Midnight audits covered 48 rendered states, 3,592 text samples, and 872 icon samples,
  with no contrast failures. Gradient stops and translucent ancestor backgrounds are
  included. Lowest ordinary text contrast was 4.51:1; lowest icon contrast was 4.61:1.
- All fixture API requests were intercepted; no unexpected requests or JavaScript
  exceptions occurred. No shared database was used.

Forty screenshots, the contrast reports, and `verification.json` are saved in
`/home/aiserver/.codex/visualizations/2026/10/09/01a11f08-6c67-7201-ac96-706da48eff33/midnight-blue/`.
Start with `midnight-blue-light-widgets.png` and `midnight-blue-dark-widgets.png`.

## Assumptions and review

- Midnight Blue keeps its existing filled custom icon family and Inter font; the new
  treatment is drawn with CSS rather than adding external assets.
- The refresh covers shared components and the main HR screens. Existing custom colours
  supplied by customer content remain customer-controlled.
- Browser QA uses Chromium and synthetic responses with all API requests intercepted.
  Review representative live tenant data and any browser-specific native date controls
  before release.

The focused usability suite is `frontend/e2e/midnight-usability.spec.ts`; run it
with `npx playwright test --config=playwright.midnight-usability.config.ts` from
`frontend/`. It covers light/dark layouts at 1440, 1024, 768, 390, and 320px, short
landscape dialogs, reduced motion, mobile breakpoint cleanup, and nested modal
keyboard behavior using intercepted synthetic APIs.

## Optimization verification

All 90 Chromium browser cases pass: 40 theme regressions, 30 celebration cases,
10 Classic motion regressions, and 10 focused usability checks. The responsive
matrix covers 30 page/viewport/mode combinations. The production build, frontend
unit suite (10 test files), lint, and whitespace checks pass. Lint retains 13
existing warnings.

The 320px Daily Analysis header is 214px tall, down from 258.5px, with all actions
inside its bounds. In a 320px-high landscape viewport, command search ends at
287.98px, compared with 322.39px before. Keyboard checks cover nested modal
closes, both Tab edges, hidden/disabled control exclusion, programmatic focus
redirection, autofocus form restoration, confirmation labels, and mobile-to-
desktop breakpoint cleanup.

Before/after screenshots, contrast reports, logs, and verification summaries are
saved under
`/home/aiserver/.codex/visualizations/2026/10/09/01a11f08-6c67-7201-ac96-706da48eff33/midnight-blue-optimized/`.
All API data is synthetic; business-data writes are rejected by the fixtures.

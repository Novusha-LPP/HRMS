# Classic Teal — original design with subtle interaction polish

Classic Teal uses the original `:root` and `.dark` tokens in
`frontend/src/index.css`. The petrol, pearl, jade, and champagne overrides and
all experimental Classic layout styles have been removed.

The original collapsible sidebar, section headings, navigation links, sidebar
account menu, breadcrumb header, rounded cards, 22px page titles, and 28px KPI
values are restored. Light/dark/system mode, theme persistence, and dashboard
widget preferences keep their existing behavior.

The Classic theme description is again “The original teal and neutral palette”.
Midnight Blue and Ember Sand remain available with their existing designs.

Nonvisual hooks required by those themes remain on shared components. The account
button has an accessible label when the sidebar is collapsed, and nested routes
highlight the most specific navigation item.

## Interaction polish

Classic keeps the original colors, fonts, card sizes, and desktop layout. A small
palette-scoped CSS block adds smoother sidebar expansion and drawer entry, a
240ms popup/menu entrance, and a one-time 440ms reveal for the celebration icon.
Pointer hover adds a 1px button lift and nav-icon nudge; stat icons gently tilt
while the cards and numbers stay in place. Disabled and pressed buttons keep
their existing behavior. A thin accent marker identifies the active sidebar
item, and keyboard focus uses the existing accent color.

On phones, nested page-header actions wrap so Attendance's Request correction
button stays inside the header. No desktop dimensions change.

All additional movement requires `prefers-reduced-motion: no-preference`.
Classic's reduced-motion mode disables animations and transitions, removes the
loading shimmer, and keeps immediate visual state feedback. Nothing remounts or
resets forms to trigger animation. Midnight Blue and Ember Sand keep their own
styles; shared dialog/sheet/icon hooks have no added appearance in those themes.

## Verification

The shared CSS rules and original base token definitions remain intact; new
styles are scoped to Classic. Browser verification covers original tokens and
geometry, sidebar collapse/reload, nested-route highlighting, light/dark/system
mode, desktop and phone screens, sign-in, and Midnight/Ember regressions.
Focused motion checks cover the finite animations, hover/pressed/disabled
states, palette switching, keyboard focus, phone layouts, popup/drawer use, and
reduced-motion behavior including the loading skeleton.

The production build and lint pass. All 80 browser cases pass: 40 theme
regressions, 30 celebration checks, and 10 focused motion cases covering
desktop/phone and light/dark modes. Real button presses retain the normal 0.98
scale; reduced-motion presses and disabled-control hovers do not transform.

Run motion QA from `frontend/` with
`npx playwright test --config=playwright.classic-motion.config.ts`. The suite
intercepts APIs with synthetic employees and rejects business-data writes.

Screenshots use synthetic tenant data. Existing Classic contrast characteristics
are preserved: subtle sidebar labels measure 4.40:1 in light mode and 4.12:1 in
dark mode; dark primary button text measures 3.74:1 and 2.49:1 on hover. These
original values remain below AA for ordinary text. Midnight and Ember retain
strict AA checks. Restoring Classic does not imply new WCAG certification.

The former phone Attendance action overflow is fixed by wrapping within the
header. The original desktop layout remains intact.

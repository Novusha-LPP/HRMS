# Classic Teal — original design restored

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
highlight the most specific navigation item. No additional visual refinement is
applied to Classic.

## Verification

All 54 shared CSS rules, including the original base token definitions, match
the Git baseline exactly. No Classic-specific CSS override remains. Production build and lint pass, and all eight unit tests pass. The full
40-case browser suite passes in Chromium, including original Classic tokens and
geometry, sidebar collapse/reload, nested-route highlighting, light/dark/system
mode, desktop and phone screens, sign-in, and Midnight/Ember regression checks.

Screenshots use synthetic tenant data. Existing Classic contrast characteristics
are preserved: subtle sidebar labels measure 4.40:1 in light mode and 4.12:1 in
dark mode; dark primary button text measures 3.74:1 and 2.49:1 on hover. These
original values remain below AA for ordinary text. Midnight and Ember retain
strict AA checks. Restoring Classic does not imply new WCAG certification.

The original phone Attendance action row remains unwrapped; Request correction
extends its local header, while the document width stays at 390px. No new
layout adjustment was applied during restoration.

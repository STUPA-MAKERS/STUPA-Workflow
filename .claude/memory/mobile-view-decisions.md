---
name: mobile-view-decisions
description: "mobile/responsive design decisions — phone bottom bar + Mehr sheet (redesign FE2, replaced the 2026-06-10 hamburger drawer), card tables, vertical stacking, 768px breakpoint"
metadata: 
  node_type: memory
  type: project
---

Mobile pass SHIPPED 2026-06-10 — merged into main (last commit 90ce447), user confirmed working. Conventions below are binding for future mobile work:

- Nav (redesign FE2, 2026-10-04; user-approved behaviour change "phone bottom bar"): at <= 768px the shell shows a fixed bottom bar (`layout/bottom-bar`) with Start, Anträge, Sitzungen (live dot), Aufgaben (count badge) and "Mehr". "Mehr" opens a bottom `app-side-sheet` with the other permitted areas, "Suche" (opens the palette) and the account menu (sheet variant). Above 768px the 96px nav rail (`layout/nav-rail`) replaces the old top header. The hamburger drawer of 2026-06-10 is gone. The shell picks rail or bar with `mediaQuerySignal(MEDIA.phone)`, not with CSS only.
- Fixed/sticky bottom elements of a page (meeting dock, selection bar, bulk bars) sit above the bar: use `bottom: var(--app-bottom-inset, 0px)`; the shell sets it on phones (bar height + safe area) and sets `--app-bottom-safe-area: 0px`, because the bar already keeps the gesture area free.
- Tables: shared data-table renders as stacked card list below breakpoint (label/value pairs from column defs).
- Multi-pane views (budget 3-pane, meeting view): stack vertically. The budget tree becomes collapsible on top.
- Scope: all pages incl. admin editors (basic usable), EXCEPT beamer view (projector-only).
- Unified mobile breakpoint: 768px. Hard constraint: desktop looks must not change — additive max-width media queries only.
- Dialogs: near-fullscreen sheet on mobile.

PWA standalone (2026-06-14, kept in FE2): `@media (display-mode: standalone)` in shell.component.scss hides the footer of the signed-in frame (kept in the browser and always in the public frame). The safe-area-inset-bottom reserve then lives on `.main` (`--main-pad-bottom`); on a phone the bottom bar carries it. Tap feedback: `-webkit-tap-highlight-color: transparent` globally kills the rectangular "inner box". The whole rounded tile recolors via `:active` on the reusable surfaces — shared data-table clickable rows, `.card--interactive`, dashboard tiles/rows/CTA. Bespoke feature tiles inherit only the highlight-kill, extend per request.

PWA bars/zoom (2026-06-14): viewport meta = `maximum-scale=1, user-scalable=no, viewport-fit=cover` (no pinch-zoom). The top status bar follows the theme: `index.html` has one `theme-color` meta per OS scheme (`#f6f7f5` light, `#101211` dark), and `ThemeService` sets both to the page background of the chosen theme (redesign FE1a, 2026-10-02; it replaced the static brand green `#004225`). Bottom Android nav bar: the user wants it to follow the active theme background. We set `html { background-color: var(--color-bg) }` for that, because Chrome samples the body/root background for the nav bar under `viewport-fit=cover`. The bottom bar and the public footer carry `env(safe-area-inset-bottom)` so the content clears the gesture pill. You can verify this only on a real installed-PWA Android device, not on a desktop.

Related: [[budget-tab-redesign]], [[sessions-protokollant-redesign]]

---
name: mobile-view-decisions
description: "mobile/responsive design decisions (2026-06-10) — hamburger drawer, card tables, vertical stacking, 768px breakpoint"
metadata: 
  node_type: memory
  type: project
---

Mobile pass SHIPPED 2026-06-10 — merged into main (last commit 90ce447), user confirmed working. Conventions below are binding for future mobile work:

- Nav: hamburger button in header → slide-in drawer with backdrop (header nav already hidden <720px with no replacement before this).
- Tables: shared data-table renders as stacked card list below breakpoint (label/value pairs from column defs).
- Multi-pane views (budget 3-pane, meetings session view): stack vertically; budget tree becomes collapsible on top.
- Scope: all pages incl. admin editors (basic usable), EXCEPT beamer view (projector-only).
- Unified mobile breakpoint: 768px. Hard constraint: desktop looks must not change — additive max-width media queries only.
- Dialogs: near-fullscreen sheet on mobile.

PWA standalone (2026-06-14): footer hidden via `@media (display-mode: standalone)` in shell.component.scss (kept in browser); safe-area-inset-bottom reserve then lives on `.main`. Tap feedback: `-webkit-tap-highlight-color: transparent` globally (kills the rectangular "inner box"); whole rounded tile recolors via `:active` on the reusable surfaces — shared data-table clickable rows, `.card--interactive`, dashboard tiles/rows/CTA. Bespoke feature tiles inherit only the highlight-kill, extend per request.

PWA bars/zoom (2026-06-14): viewport meta = `maximum-scale=1, user-scalable=no, viewport-fit=cover` (no pinch-zoom). Top status bar stays brand green via static `theme-color` `#004225`. Bottom Android nav bar: user wants it to follow the active theme bg — done by setting `html { background-color: var(--color-bg) }` (Chrome samples body/root bg for the nav bar under `viewport-fit=cover`); footer got `padding-bottom: env(safe-area-inset-bottom)` so content clears the gesture pill. Only verifiable on a real installed-PWA Android device, not desktop.

Related: [[budget-tab-redesign]], [[sessions-protokollant-redesign]]

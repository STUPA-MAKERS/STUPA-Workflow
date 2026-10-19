---
name: mobile-view-decisions
description: "Binding mobile/responsive rules: 768px breakpoint, additive media queries only, phone bottom bar + Mehr sheet, bottom inset for fixed elements, footer only on start and public pages, PWA bar colours"
metadata:
  node_type: memory
  type: project
---

Binding rules for mobile work. The frame details are in the `frontend` skill
(`src/app/layout/`).

- **One breakpoint: 768px** (`MEDIA.phone` of the ui-kit, `(max-width: 768px)`). Desktop looks
  must not change: add max-width media queries only. Scope is every page, the admin editors
  included (basic usable), EXCEPT the beamer view (projector only).
- **Navigation:** at <= 768px the shell shows the fixed bottom bar (`layout/bottom-bar`) with
  Start, Anträge, Sitzungen, Aufgaben (`BOTTOM_BAR_KEYS`) and "Mehr". "Mehr" opens a bottom
  `app-side-sheet` with the other permitted areas, "Suche" and the account menu. Above 768px
  the 96px nav rail (`layout/nav-rail`) has a "Suche" button, so search is in reach on every
  page without a keyboard. The shell picks rail or bar with `mediaQuerySignal(MEDIA.phone)`,
  not with CSS only. There is no hamburger drawer.
- **Fixed or sticky bottom elements** of a page (meeting dock, selection bar, ballot, wizard
  nav, FAB) sit above the bar: `bottom: var(--app-bottom-inset, 0px)`. On a phone the shell sets
  it to bar height + safe area, and sets `--app-bottom-safe-area: 0px`, because the bar already
  keeps the gesture area free. Route data `fab: true` adds `--app-fab-clearance` to the body
  padding, so the FAB never covers the end of the page.
- **Tables** (kit data table) become a stacked card list on a phone. **Multi-pane pages** show
  one pane at a time; the budget tree moves into a side sheet behind a path chip. **Dialogs**
  become a near-fullscreen sheet.
- **Footer:** only on the start page and the public pages (route data `footer: true`; the
  public frame always shows it). Work pages have no footer. An installed PWA
  (`@media (display-mode: standalone)` in `shell.component.scss`) hides the footer of the
  signed-in frame and moves the safe-area reserve to `.main`.
- **Tap feedback:** the kit base styles set `-webkit-tap-highlight-color: transparent` on every
  element, because the default highlight is a rectangle that ignores the rounded tile. The
  reusable surfaces (clickable data-table rows, `.card--interactive`, list-item rows) tint the
  whole tile on `:active` instead.
- **PWA bars and zoom:** the viewport meta is `maximum-scale=1, user-scalable=no,
  viewport-fit=cover` (no pinch zoom). `index.html` has one `theme-color` meta per OS scheme,
  and `ThemeService` sets both to the page background of the chosen theme, so the status bar
  follows the theme. The kit sets `html { background-color: var(--color-bg) }`, because Chrome
  on Android colours its nav bar from the root background under `viewport-fit=cover`. The
  bottom bar and the public footer carry `env(safe-area-inset-bottom)`. You can verify the bar
  colours only on a real Android device with the installed PWA, not on a desktop.

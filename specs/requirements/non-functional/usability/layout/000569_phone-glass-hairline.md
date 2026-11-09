---
id: "000569"
title: A glass bar on the phone ends in a hairline
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/styles/tokens.scss
  - frontend/vendor/ui-kit/src/lib/sticky-bar
  - frontend/vendor/ui-kit/src/lib/list-group
  - frontend/vendor/ui-kit/src/lib/list-detail
  - frontend/vendor/ui-kit/shell/src/bottom-bar
  - frontend/src/app/layout/public-header
  - frontend/src/app/pages/todos
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A glass bar on the phone ends in a hairline

On a phone, the edge of a glass bar must be a hairline in the border colour, the same line as
the tab line of a tab pager. The edge must not have a shadow. This rule applies to the
navigation bar at the bottom, the bar at the top of a page, the search bar of a list, a pinned
group head and the bar of the public pages. A bar that floats with a gap to the screen edges,
for example the dock of a meeting, keeps its shadow. A wide screen keeps its shadows.

Reason: All glass edges on the phone look the same as the tab line. A shadow under glass is a
second soft edge on a surface that already shows the content blurred behind it.

Test: `frontend/vendor/ui-kit/shell/src/bottom-bar/bottom-bar.styles.spec.ts`,
`frontend/src/app/layout/bottom-bar/bottom-bar.styles.spec.ts` and a check of the screenshots.

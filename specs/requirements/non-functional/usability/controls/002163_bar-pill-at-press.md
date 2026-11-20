---
id: "002163"
title: The pill of the navigation bar moves at the press
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/shell/src/bottom-bar/bottom-bar.component.spec.ts:BottomBarComponent"
implementation:
  - frontend/vendor/ui-kit/shell/src/bottom-bar/bottom-bar.component.ts
  - frontend/vendor/ui-kit/src/styles/_nav-items.scss
scope:
  - frontend/vendor/ui-kit/shell
  - frontend/vendor/ui-kit/src/styles
---

# The pill of the navigation bar moves at the press

The pill of the bottom bar must go to the pressed entry at the press (`pointerdown`), before
the new page renders. Every switch must show the same animation: the old pill fades and the new
one grows. The animation must change only `opacity` and `scale`. When the press starts no
navigation, the pill must go back to the active entry.

Reason: The active mark followed the router, so it moved only after the new page had rendered.
On a slow page it moved late, and in a view transition it sometimes jumped. An animation of
`opacity` and `scale` runs on the compositor and does not stop while the page renders.

Test: The tests of the bottom bar check that a press marks the entry before the navigation and
that a press without a navigation clears the mark. A person checks the look on recordings.

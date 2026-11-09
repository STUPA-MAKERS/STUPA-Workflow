---
id: "000567"
title: A phone FAB folds to its icon on scroll
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/lib/fab/fab.component.ts
  - frontend/vendor/ui-kit/src/lib/fab/fab.component.scss
scope:
  - frontend/vendor/ui-kit
---

# A phone FAB folds to its icon on scroll

On a phone, a FAB must show its icon and its label while the page is at the top. When the
page scrolls down, the label must fade out and the FAB must shrink to a square of 56px in
`--motion-base`. When the page is at the top again, the label must come back. With reduced
motion, the change must have no transition. The label must stay the accessible name of the
FAB.

Reason: The label tells what the FAB does on the first view. While the user reads the list,
the full FAB covers too much of it.

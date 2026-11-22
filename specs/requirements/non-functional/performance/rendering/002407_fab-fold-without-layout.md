---
id: "002407"
title: The FAB fold runs between two measured sizes and ends in the folded layout
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-22
tests:
  - "frontend/vendor/ui-kit/src/lib/fab/fab.component.spec.ts:FabComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/fab/fab.component.ts
  - frontend/vendor/ui-kit/src/lib/fab/fab.component.scss
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app
---

# The FAB fold runs between two measured sizes and ends in the folded layout

While a phone FAB folds to its icon or unfolds (kit spec 000567), the width of the button must
run from its measured width to the 56px square, and the padding before the icon must run to
the padding that centres the icon. The content must start at the start edge, and the button
must clip what does not fit, so the icon keeps its place and the label is cut at the end edge
while it fades out in the first half. The last frame of the animation must be the folded
layout, pixel for pixel. The FABs before it in a group must follow in the layout. A change of
direction while the animation runs must turn it round. With reduced motion, the size must
change at once.

Reason: The old fold moved `max-width` from 14rem, so its first half showed no change and its
second half snapped. A fold that split a clip on the main thread from a slide and a fade on the
compositor ran out of step on a phone that was busy with the scroll, and it jumped at the end,
where its computed look met the real layout. One size animation on the real layout keeps
every part in step and has nothing to meet at the end.

Test: The test of the FAB checks the keyframes of the width and the padding, that the folded
class comes at the end, that a change of direction turns the animation round, and that
reduced motion folds at once.

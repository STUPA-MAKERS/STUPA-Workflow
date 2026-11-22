---
id: "002407"
title: The FAB fold animates only clip, transform and opacity
kind: non-functional
status: draft
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

# The FAB fold animates only clip, transform and opacity

While a phone FAB folds to its icon or unfolds (kit spec 000567), its size must not change. A
clip must cut the button from its start towards its end, with the round corners of the button
at the cut. The icon must slide to the centre of the square, and the label must fade out in
the first half. The FABs before it in a group must slide along. Only when the animation ends
must the button take its folded size, which looks the same. The unfold must take the full size
first and open the clip. A change of direction while the animation runs must turn it round.
With reduced motion, the size must change at once.

Reason: A width, a padding or a gap that moves lays out and paints the button and its group
in every frame. The old fold also moved `max-width` from 14rem, so its first half showed no
change and its second half snapped. On a Pixel 7 with a 4× slower CPU the fold cost 10 to 19 ms
of layout and 33 to 65 ms of paint, and now costs 1 to 3 ms and 16 to 20 ms.

Test: The test of the FAB checks that the fold animates only `clip-path`, `transform` and
`opacity`, that the folded class comes at the end, that a change of direction turns the
animations round, and that reduced motion folds at once.

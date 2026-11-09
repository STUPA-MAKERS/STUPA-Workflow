---
id: "000528"
title: A pressed segment shrinks only its pill
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/styles/_press.scss
  - frontend/vendor/ui-kit/src/lib/segmented/segmented.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A pressed segment shrinks only its pill

A press on a segment of a segmented control must shrink only the pill inside the track, by
the control amount (0.94). The track must not shrink. A press on the chosen segment shrinks
the chosen pill and gives it the press tint. A press on another segment gives that segment
the press tint as a pill and shrinks that pill.

Reason: The track has no border and does not clip its segments, so a pill that shrinks
leaves no gap. A track that shrinks moves the whole row, and the press reads as a jump of
the layout.

Test: `touch.spec.ts` of the ui-kit reads the press of the segmented control.

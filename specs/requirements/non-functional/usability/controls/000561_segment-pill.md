---
id: "000561"
title: A segmented control is a pill track
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
tests:
  - "frontend/vendor/ui-kit/src/lib/segmented/segmented.component.spec.ts:SegmentedComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/segmented/segmented.component.scss
  - frontend/vendor/ui-kit/src/lib/segmented/segmented.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A segmented control is a pill track

A segmented control must be a filled pill track without a border and without dividers. The
chosen segment must be a fully rounded pill inside the track, filled with the primary colour
mixed into the surface, with a bold label. The other labels must use the muted text colour.
A segment must not show a check mark.

When the user chooses a different segment, the pill must slide from the old segment to the
new one and take the width of the new segment (`--motion-base`, `--ease-standard`). The
labels change their colour in the same time. With reduced motion, the pill must not slide: it
shows at the new segment at once. When the control shows for the first time, the pill must
not slide in.

Reason: One filled pill marks the choice more clearly than a border with dividers and a check
mark, and it uses less width on a phone. A pill that slides shows where the choice went.

Test: `segmented.component.spec.ts` of the ui-kit checks that no segment has a check mark and
that one pill moves to the chosen segment. A person checks the look and the slide on
screenshots and a recording in both themes.

---
id: "000561"
title: A segmented control is a pill track
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/vendor/ui-kit/src/lib/segmented/segmented.component.spec.ts:SegmentedComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/segmented/segmented.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A segmented control is a pill track

A segmented control must be a filled pill track without a border and without dividers. The
chosen segment must be a fully rounded pill inside the track, filled with the primary colour
mixed into the surface, with a bold label. The other labels must use the muted text colour.
A segment must not show a check mark.

Reason: One filled pill marks the choice more clearly than a border with dividers and a check
mark, and it uses less width on a phone.

Test: `segmented.component.spec.ts` of the ui-kit checks that no segment has a check mark. A
person checks the look on screenshots in both themes.

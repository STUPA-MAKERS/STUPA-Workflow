---
id: "001314"
title: A press shows a ripple
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/styles/touch.spec.ts:ripple"
implementation:
  - frontend/vendor/ui-kit/src/styles/_press.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A press shows a ripple

Every clickable element must show a ripple on press: a circle in the press tint that starts at
the point of the press and grows until it fills the whole element. The ripple must be clipped to
the shape of the element. It must stay while the press lasts and must fade out after the
release. A press with Enter or Space must start the ripple in the centre of the element. Rows,
cards and tiles get the same ripple as buttons, chips and segments. No element must shrink on
press. Prose links and text inputs must not show a ripple. With reduced motion, the ripple must
not grow: the whole element shows the press tint at once (000410).

Reason: A ripple shows where the press landed and does not move the edges of the element, so the
layout does not jump and a group that clips its parts keeps its border.

Test: `touch.spec.ts` of the ui-kit checks that no press rule sets `scale` and that every press
draws the ripple. A person checks the look on recordings in both themes and in the display
settings.

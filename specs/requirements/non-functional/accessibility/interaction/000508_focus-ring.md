---
id: "000508"
title: The focus ring is 2 px and has a contrast of 3:1
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The focus ring is 2 px and has a contrast of 3:1

Every focused control must show a focus ring of at least 2 px. The ring must have a contrast
of at least 3:1 to the colours next to it. A style must not remove the outline without this
ring.

Reason: WCAG 2.4.7 and 2.4.13.

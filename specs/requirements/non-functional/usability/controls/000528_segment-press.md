---
id: "000528"
title: A pressed segment shrinks its whole control
kind: non-functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-19
replaced_by: NF/usability/controls/001315
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A pressed segment shrinks its whole control

A pressed segment of a segmented control must get the press tint, and the whole control must
shrink by the row amount (0.98). A segment must not shrink alone.

Reason: The control clips its segments to one rounded border. A segment that shrinks alone
pulls its fill away from the border, and the gap looks like a broken control.

Test: `touch.spec.ts` of the ui-kit reads the press of the segmented control.

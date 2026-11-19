---
id: "001351"
title: A selected button of a group is filled and fully round
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/button-group/button-group.component.spec.ts:ButtonGroupComponent"
implementation:
  - frontend/vendor/ui-kit/src/styles/button-group.scss
  - frontend/src/app/pages/applications/applications-detail.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A selected button of a group is filled and fully round

A button of a head group (001350) that is pressed or whose menu or sheet is open must have the
accent fill and round all four corners to half its height. The other buttons of the group must
keep their shape. "Kommentare" of an Antrag counts as open while its comment sheet is open.

Reason: The change of shape and fill shows which part of the head is open, as the connected
button group of Material 3 does.

Test: The spec of `ButtonGroupComponent` in the ui-kit expects the fill and the full radius
for a button with `aria-expanded="true"`.

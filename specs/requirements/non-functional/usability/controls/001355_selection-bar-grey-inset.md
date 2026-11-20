---
id: "001355"
title: The selection bar in a list is a grey surface with an inset around its actions
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/lib/selection-bar/selection-bar.component.scss
scope:
  - frontend/vendor/ui-kit
---

# The selection bar in a list is a grey surface with an inset around its actions

The selection bar that stands in the flow of a list ("3 ausgewählt") must have a grey surface,
not the colour of a selected row. It must have the same inset of 8 px above, below and after its
actions, so it is higher than its buttons, and its corners must be concentric with the round
ends of its buttons.

Reason: The selected colour made the bar look like one more selected row, and the buttons
touched its upper and lower edge.

Test: Screenshots of the Antrag list with rows selected, on a wide screen and on a phone, in
the light and the dark theme and in the very high contrast mode.

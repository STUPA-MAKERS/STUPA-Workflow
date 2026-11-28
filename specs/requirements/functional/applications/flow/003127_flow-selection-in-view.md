---
id: "003127"
title: A selected item of the flow moves into view
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
implementation:
  - frontend/src/app/pages/admin/flow/flow-canvas-interaction.ts
scope:
  - frontend/src/app/pages/admin/flow
---

# A selected item of the flow moves into view

When a state or a transition is selected and is not fully in the visible part of the canvas,
the canvas must pan until it is fully visible, beside the inspector sheet. The zoom must not
change. The pan must not move when the item is already fully visible.

Reason: A selection from the transition lists of the inspector, or a state at the edge, opened
an item that the reader could not see.

Test: A unit test selects a state outside the view and expects the view to contain it.

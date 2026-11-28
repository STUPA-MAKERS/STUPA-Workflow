---
id: "003124"
title: The flow layout runs from the initial state to the terminal states
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
implementation:
  - frontend/src/app/pages/admin/flow/flow-elk.ts
scope:
  - frontend/src/app/pages/admin/flow
---

# The flow layout runs from the initial state to the terminal states

The automatic layout of the flow canvas must put the initial state (with its start event) in
the first layer on the left and the terminal states (with their end events) in the last layer
on the right. The layout must order the other states by their distance from the initial state
along the transitions. The order of the keys must not change the layout. A transition back to an
earlier state must run as a back edge, not move its target to the front.

Reason: The layout took the alphabetical order of the keys as the order of the flow. A terminal
state such as one with a key that starts with "a" stood first, and the flow read backwards
with long lines around the whole graph.

Test: A unit test lays out a flow whose terminal key sorts first and expects the initial state
in the first layer and the terminal state in the last layer.

---
id: "003123"
title: The flow canvas draws the flow in BPMN notation
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
implementation:
  - frontend/src/app/pages/admin/flow/flow-editor.component.html
  - frontend/src/app/pages/admin/flow/flow-canvas-view.ts
scope:
  - frontend/src/app/pages/admin/flow
---

# The flow canvas draws the flow in BPMN notation

The canvas of the flow editor must draw the flow with the shapes of BPMN 2.0:

- A start event (a thin circle) must stand before the initial state, with a sequence flow to it.
- A state must be a task: a box with rounded corners and its name in the middle.
- A terminal state must have a sequence flow to an end event (a thick circle) after it.
- A vote state must be a task with a vote marker in its top-left corner, followed by an
  exclusive gateway (a diamond with an X). Its branches must leave the gateway, each labelled
  with its branch.
- A transition must be a sequence flow: a solid line with a filled arrow head. A transition with
  a guard must have the conditional marker (a small open diamond) at its start. An automatic
  transition must show a lightning marker before its label.
- A closed group must be a collapsed sub-process: a task with a [+] marker at the bottom. An
  open group must show its members inside the frame of an expanded sub-process.
- The connector handles of a task must show only on hover and on the selected task.

The colours of the states, transitions and groups stay as configured. The legend must name the
start event, the end event, the gateway and the automatic transition.

Reason: Readers of the flow know BPMN, and the notation shows start, end and decisions at a
glance.

Test: A unit test of the canvas view expects a start event before the initial state, an end
event after each terminal state and a gateway after each vote state.

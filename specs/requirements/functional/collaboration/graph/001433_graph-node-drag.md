---
id: "001433"
title: A drag moves a node of the graph
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/graph/graph-canvas.component.spec.ts:GraphCanvasComponent"
implementation:
  - frontend/src/app/pages/graph/graph-canvas.component.ts
  - frontend/src/app/pages/graph/graph-layout.ts
scope:
  - frontend/src/app/pages
---
# A drag moves a node of the graph

A drag on a node must move the node with the pointer. The node must stay where the person lets
go: the layout must not move it again. The nodes that connect to it must follow while it moves.
With reduced motion (F/collaboration/graph/001427) only the dragged node moves. A pointer that
travels less than a press must still choose the node, and the click at the end of a drag must
not choose it. Alt with an arrow key must move the focused node by one step in that direction
and hold it the same way. The place of a node is part of the view only: a reload, a new filter
or a node that leaves the drawing drops it.

Reason: The layout places the nodes by force and does not know what the person wants to
compare. The person pulls two elements side by side or pulls a knot apart. Dragging alone
would shut out a person without a pointer, so the keyboard does the same.

Test: A frontend unit test drags a node and checks its place, the hold and the press that
follows; one moves a node with the keyboard; one runs the layout with a held node.

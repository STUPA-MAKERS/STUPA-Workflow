---
id: "001429"
title: A press on a node shows the element and its neighbours
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/pages/graph
scope:
  - frontend/src/app/pages
---
# A press on a node shows the element and its neighbours

A press on a node must choose it. The drawing must then dim every node that is not a neighbour
of the chosen node, and a panel must show the kind, the title, the date and the state of the
element and the action "Öffnen" (`Open`). The panel must not list the neighbours: the drawing
shows them. On a phone the panel must be a sheet from the foot of the screen. "Öffnen" must go to the detail of the element. A press on
the empty drawing must end the choice. A drag on the empty drawing must move the view (a drag on a node moves the node,
F/collaboration/graph/001433), and the
wheel, a pinch and the buttons "+" and "−" must zoom it.

Reason: A person first reads how an element connects, and opens it only when it is the right
one. A press that leaves the page at once would lose the place in the graph.

Test: A frontend unit test presses a node and checks the dimmed nodes, the panel and the
target of "Öffnen".

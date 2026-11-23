---
id: "002790"
title: "Mehr laden" of the graph stands over the zoom buttons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/graph/graph.component.spec.ts:GraphComponent"
implementation:
  - frontend/src/app/pages/graph/graph.component.html
  - frontend/src/app/pages/graph/graph.component.scss
scope:
  - frontend/src/app/pages
---

# "Mehr laden" of the graph stands over the zoom buttons

The state of the build-up of the graph ("Weitere Elemente werden geladen …" and "Mehr laden")
must stand over the zoom buttons of the drawing, at their end edge, with a gap of 8px, on every
width. It must not be in the foot beside "Schritte".

"Mehr laden" must be one tonal button of the control height (40px), the look of the zoom
buttons. It must have no icon and no surface around it. "Weitere Elemente werden geladen …"
must be a pill of the same height on surface 1, with muted text.

Reason: In the foot the button took the room of the zoom buttons, and on a phone it lay over
them. A small button in a second pill, with a chevron that points down, looked like a part of
a list and not of the drawing. Over the zoom buttons it has room on every width and has the
look of the tools of the drawing.

Test: A frontend unit test finds "Mehr laden" in the layer over the drawing and not in the
foot, checks the tonal look without an icon, and finds the state of the build-up at the same
place.

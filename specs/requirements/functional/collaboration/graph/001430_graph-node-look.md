---
id: "001430"
title: A node shows the icon and the colour of its kind
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - frontend/src/app/pages
---
# A node shows the icon and the colour of its kind

A node must show the icon of its kind (F/collaboration/links/001407) on a fill in the colour
of its kind. The title must show under the node from a zoom step at which it is readable, and
always for the chosen node and its neighbours. A legend must name each kind with its icon and
colour. A press on a kind in the legend must switch the kind in the filter "Art". The page
must not show a count of the nodes of a kind.

Reason: The icon tells the kind without colour (NF/accessibility/perception/000502). Titles
on every node at every zoom step would cover each other.

Test: A frontend unit test renders one node of each kind and checks the icon and the legend.

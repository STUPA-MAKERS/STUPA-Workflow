---
id: "001428"
title: The graph has a list view
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/graph
scope:
  - frontend/src/app/pages
---
# The graph has a list view

The page must have the views "Graph" and "Liste" (`List`). The list must show the same nodes with
the same filters, one row per node with the icon of its kind, the title, the date and its neighbours
as links. With a screen reader the drawing must be one group with a label that names the count of
nodes and lines and points to the list, and each node must be a button with the kind and the title
as its name. A person must reach each node of the drawing with the keyboard: Tab moves into the
drawing, the arrow keys move to the nearest node in that direction, Enter chooses the node.

Reason: NF/accessibility/perception/000507 and WCAG 2.1.1. A screen reader cannot read a
drawing, and a pointer must not be the only way to a node.

Test: A frontend unit test switches to the list and compares the rows with the nodes, and
moves the focus with the arrow keys.

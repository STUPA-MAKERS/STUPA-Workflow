---
id: "001428"
title: The drawing has a text alternative
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/graph
scope:
  - frontend/src/app/pages
---
# The drawing has a text alternative

With a screen reader the drawing must be one group with a label that names the count of nodes
and lines. Each node must be a button with the kind and the title as its name, and with its
neighbours as its description. A person must reach each node of the drawing with the keyboard:
Tab moves into the drawing, the arrow keys move to the nearest node in that direction, Enter
chooses the node. The page must not have a list view.

Reason: NF/accessibility/perception/000507 and WCAG 2.1.1. A screen reader cannot read a
drawing, and a pointer must not be the only way to a node. The names and the descriptions of
the nodes are the text of the drawing, so a second view with the same content is not needed.

Test: A frontend unit test reads the name and the description of a node, and moves the focus
with the arrow keys.

---
id: "001427"
title: The graph does not move with reduced motion
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - frontend/src/app/pages
---
# The graph does not move with reduced motion

With reduced motion (NF/accessibility/interaction/000219) the graph must show each page of
nodes at its final place, without scale-in and without a moving layout.

Reason: A layout that settles moves every node on the page at once, which is the motion that
the setting is for.

Test: A frontend unit test with the motion setting on checks that the layout runs to its end
before the first paint of a page.

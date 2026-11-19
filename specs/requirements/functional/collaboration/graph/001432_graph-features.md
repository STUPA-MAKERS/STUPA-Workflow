---
id: "001432"
title: A kind of a feature that is off does not show in the graph
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# A kind of a feature that is off does not show in the graph

The graph must not show a node of a kind whose feature is off
(F/administration/admin/000757), and the filter "Art" and the legend must not offer the kind.

Reason: A feature that is off does not show anywhere in the UI
(F/administration/admin/000758).

Test: A backend unit test switches `Rechnungen` off and reads a graph that has no invoice
node.

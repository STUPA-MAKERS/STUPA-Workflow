---
id: "000328"
title: Search reuses the gate of each module
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/search
  - frontend/src/app/layout
---

# Search reuses the gate of each module

The global search must not have a gate of its own. Each source must call the listing of its
module with the same scope as the module route. A source without the permission must answer
nothing, without a database query.

Reason: A permission change in a module then reaches the search by itself.

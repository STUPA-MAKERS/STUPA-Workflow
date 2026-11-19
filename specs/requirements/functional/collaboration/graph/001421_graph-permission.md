---
id: "001421"
title: The graph needs its own permission
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
  - frontend/src/app/pages
---
# The graph needs its own permission

The page "Graph" and its API must need the global permission `graph.view`. Without it the API
must answer 403, and the navigation must not show the entry. The permission must be a key of
the permission catalog. No seeded role but the admin role must hold it. The permission must
open the page only. It must not give read access to an element.

Reason: The graph shows many elements of many areas at once. An admin decides who gets this
overview, apart from the read rights of each area.

Test: A backend unit test reads `GET /api/graph` without the permission and gets 403. A
frontend unit test of the navigation hides the entry without the permission.

---
id: "001482"
title: The form editor and the flow editor open without the list
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/app.routes.ts
scope:
  - frontend/src/app/pages/admin/forms
  - frontend/src/app/pages/admin/flow
---

# The form editor and the flow editor open without the list

The form editor (`/admin/forms/:id`) and the flow editor (`/admin/flow`) must open as pages of
their own at the full width, without the list of Verwaltung beside them. Their URLs stay the
same. On a wide screen, they fill the free height, and their columns scroll inside themselves.

Reason: The canvas and the columns of the editors need the full width.

Test: A unit test of the routes expects both editors outside the list page of Verwaltung.

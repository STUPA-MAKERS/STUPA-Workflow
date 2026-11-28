---
id: "003130"
title: The form editor and the flow editor open in the detail pane
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/pages/admin/admin-list/admin-pages.spec.ts:adminEditors"
implementation:
  - frontend/src/app/app.routes.ts
scope:
  - frontend/src/app/pages/admin/forms
  - frontend/src/app/pages/admin/flow
---

# The form editor and the flow editor open in the detail pane

The form editor (`/admin/forms/:id`) and the flow editor (`/admin/flow`) must open in the
detail pane of Verwaltung, beside the list of Verwaltung, like every other admin page. Their
URLs stay the same. In the pane, the editors fill the free height, and their columns scroll
inside themselves. The layout of an editor must follow the width of the pane, not the width of
the window. On the phone, the pane is the whole screen, as for every other admin page.

Reason: The editors are admin pages like the others, and the list of Verwaltung stays the way
to the next page.

Test: A unit test of the routes expects both editors as children of the list page of
Verwaltung.

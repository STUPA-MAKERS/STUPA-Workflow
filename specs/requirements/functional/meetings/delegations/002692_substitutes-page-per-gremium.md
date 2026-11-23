---
id: "002692"
title: The Stellvertretungen of a Gremium have their own page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/committees/substitute-pool.component.spec.ts:SubstitutePoolComponent"
  - "frontend/src/app/pages/admin/committees/gremien.component.spec.ts:AdminGremienComponent"
implementation:
  - frontend/src/app/pages/admin/committees/substitute-pool.component.ts
  - frontend/src/app/pages/admin/committees/gremien.component.ts
  - frontend/src/app/app.routes.ts
scope:
  - frontend/src/app/pages/admin
---

# The Stellvertretungen of a Gremium have their own page

The substitute pool of a Gremium (000112) must be its own page `/admin/committees/<id>/substitutes`,
the same as the Mitglieder (`/admin/committees/<id>/members`). The ⋮ menu of a Gremium on the
Gremien page must open it with the entry "Stellvertretungen", directly after "Mitglieder". The
page must be a list page of Verwaltung (002690) with the action "Stellvertretung hinzufügen".

The page Vertretung / Delegation must show only the delegations, not the pool.

Reason: The pool belongs to one Gremium, but it stood at the end of Vertretung / Delegation
behind a Gremium picker (Frederik 2026-11-23).

Test: A unit test of the Gremien page expects the menu entry and its link. A unit test of the
pool page expects the records screen with the Gremium from the route.

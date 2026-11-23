---
id: "002620"
title: The Benutzer page has no link to the Gruppen-Zuordnung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/users/users.component.spec.ts:has no link to the group mappings"
implementation:
  - frontend/src/app/pages/admin/users/users.component.html
scope:
  - frontend/src/app/pages/admin/users
---

# The Benutzer page has no link to the Gruppen-Zuordnung

The page Verwaltung › Benutzer must not show a note row with a link to the page
Gruppen-Zuordnung. The list must start directly below the search.

Reason: The Verwaltung menu already leads to the Gruppen-Zuordnung. A second way in on top of
the list takes a row and adds nothing.

Test: The unit test of the users page finds no link to `/admin/group-mappings`.

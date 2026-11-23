---
id: "002620"
title: Benutzer and Gremien have no link to the Gruppen-Zuordnung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/users/users.component.spec.ts:UsersComponent"
  - "frontend/src/app/pages/admin/committees/gremien.component.spec.ts:AdminGremienComponent"
  - "frontend/src/app/pages/admin/committees/gremium-members.component.spec.ts:GremiumMembersComponent"
implementation:
  - frontend/src/app/pages/admin/users/users.component.html
  - frontend/src/app/pages/admin/committees/gremien.component.html
  - frontend/src/app/pages/admin/committees/gremium-members.component.html
scope:
  - frontend/src/app/pages/admin/users
  - frontend/src/app/pages/admin/committees
---

# Benutzer and Gremien have no link to the Gruppen-Zuordnung

The pages Verwaltung › Benutzer, Verwaltung › Gremien and the members page of a Gremium must
not show a note row with a link to the page Gruppen-Zuordnung.

Reason: The Verwaltung menu already leads to the Gruppen-Zuordnung. A second way in on top of
the page takes a row and adds nothing.

Test: The unit tests of the three pages find no link to the Gruppen-Zuordnung.

---
id: "002600"
title: Gremium verwalten opens the Gremium on the Gremien page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.spec.ts:GremiumDetailComponent"
implementation:
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.ts
scope:
  - frontend/src/app/features/gremien
---

# Gremium verwalten opens the Gremium on the Gremien page

The action "Gremium verwalten" of the detail page of a Gremium must open the Gremien page of
the Verwaltung (`/admin/committees`) with the query parameter `open=<gremium id>`. The action
must not open the members page of the Gremium. The button in the head and the entry in the ⋮
menu of the phone are the same action.

Reason: The settings and the roles of a Gremium are on the Gremien page. The members page shows
only one part of the Gremium.

Test: A frontend test that the button and the menu entry open `/admin/committees?open=<id>`.

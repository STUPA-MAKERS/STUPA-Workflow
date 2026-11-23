---
id: "002690"
title: Every list page of Verwaltung looks like Benutzer
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/admin-list-search.spec.ts:adminListPages"
implementation:
  - frontend/vendor/ui-kit/screens/src/records-screen/records-screen.component.ts
  - frontend/src/app/pages/admin/list-search.ts
scope:
  - frontend/src/app/pages/admin
---

# Every list page of Verwaltung looks like Benutzer

Each page of Verwaltung that lists records must be built on the records screen of the kit
(`app-records-screen`, ui-kit:002257), the same as Benutzer. Its search row must be the search of
Benutzer: an `app-search-pill` of size `md` with the × button and the count of hits, in the sticky
bar above the filter chips. The records must be rows of one row group, not a table.

These pages are list pages: Benutzer, Rollen & Rechte, Agent-Zugänge, Gremien, the Mitglieder of a
Gremium, the Stellvertretungen of a Gremium, Vertretung / Delegation, Haushalte, Kalender,
Webhooks, Dokument-Varianten and Erzwungene Statusänderungen.

Reason: Each list page of Verwaltung had its own head, its own list and mostly no search, and
Haushalte was a table. Frederik wants one layout and one search bar on all of them
(2026-11-23).

Test: A unit test of each listed page expects `app-records-screen` with an `app-search-pill` in
the search slot. A person checks the look on screenshots in both themes and in the display
settings.

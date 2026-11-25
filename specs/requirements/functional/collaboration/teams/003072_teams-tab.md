---
id: "003072"
title: The tab Gremien is the tab Teams
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - frontend/src/app/features/gremien
  - frontend/src/app/app.routes.ts
---

# The tab Gremien is the tab Teams

The navigation tab Gremien must be named Teams and open `/teams`. The old route `/committees`
must lead to `/teams`. The list must show the teams of the person, each sub-team under its
parent. The page of an inherent team must show the tabs of its Gremium as today. The page of
another team must show the tabs Board, Mitglieder, Sub-Teams and Info.

Reason: Every Gremium is a team, so one tab shows both.

Test: A frontend unit test opens `/committees` and lands on `/teams`, and an e2e test opens a
team page.

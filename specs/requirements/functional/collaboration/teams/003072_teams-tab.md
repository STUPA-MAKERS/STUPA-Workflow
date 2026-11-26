---
id: "003072"
title: The tab Gremien is the tab Teams
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - frontend/src/app/features/gremien/gremien-page/gremien.component.ts
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.ts
  - frontend/src/app/features/gremien/team-sub-teams/team-sub-teams.component.ts
  - frontend/src/app/app.routes.ts
scope:
  - frontend/src/app/features/gremien
  - frontend/src/app/app.routes.ts
---

# The tab Gremien is the tab Teams

The navigation tab Gremien must be named Teams and open `/teams`. The old route `/committees`
must lead to `/teams`. The list must show the teams of the person, each sub-team under its
parent. Each row must show the name and the number of members of the team, and "Läuft" while a
meeting of its Gremium runs. A row must not show a role, the parent team or a meeting date. The page of an inherent team must show the tabs of its Gremium as today, plus the tab
Sub-Teams. The tabs Sitzungen, Beschlüsse and Anwesenheit must exist only on the page of an
inherent team. The page of another team must show only the tabs Board, Mitglieder, Sub-Teams and
Info.

Reason: Every Gremium is a team, so one tab shows both.

Test: A frontend unit test opens `/committees` and lands on `/teams`, and an e2e test opens a
team page.

---
id: "003062"
title: A team can have sub-teams
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
  - frontend/src/app/features/gremien
---

# A team can have sub-teams

A team must be able to have any number of sub-teams, and a sub-team can have sub-teams. A
team must not be its own parent or ancestor. The parent of an inherent team must be empty. A
team that has sub-teams must not be deleted (409 `team_has_sub_teams`).

Reason: A Gremium splits its work into Referate and work groups. The tree shows where a team
belongs.

Test: A backend unit test builds a tree of three levels and refuses a parent that makes a
cycle.

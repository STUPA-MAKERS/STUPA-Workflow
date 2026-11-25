---
id: "003066"
title: team.manage in a Gremium role manages the inherent team
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
---

# team.manage in a Gremium role manages the inherent team

A member of a Gremium whose Gremium role holds the new permission `team.manage` must manage
the inherent team of the Gremium: its sub-teams, its board settings and its Info. The data
migration must give `team.manage` to every Gremium role that holds `todo.configure`.

Reason: The inherent team has no hand-made managers, so the Gremium roles decide.

Test: A backend test gives `team.manage` to a Gremium role and creates a sub-team as a member
with that role.

---
id: "003067"
title: Every team has its own board
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/todos
  - backend/app/modules/gremien
  - backend/migrations
---

# Every team has its own board

Every team must have exactly one own board. A board must be linked to its team, never to a
Gremium: the board row must store the team and must not store a Gremium. The data migration must
link the board of each Gremium to the inherent team of that Gremium, so its cards, columns and
links stay. Code that needs the Gremium of a board must find it through the team. Each member of the team must
edit the board, and each manager of the team must manage it. The extra entries of the board must
add their roles as today. This replaces 001078.

Reason: The team decides the board access, not the Gremium.

Test: A backend test reads the board of a new team as a member and as a manager, and gets 404 as
a person outside the team.

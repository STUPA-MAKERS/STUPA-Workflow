---
id: "003067"
title: Every team has its own board
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/todos
  - backend/app/modules/gremien
  - backend/migrations
---

# Every team has its own board

Every team must have exactly one own board. The board of an inherent team must be the board
that the Gremium has today, so its cards, columns and links stay. Each member of the team must
edit the board, and each manager of the team must manage it. The extra entries of the board must
add their roles as today. This replaces 001078.

Reason: The team decides the board access, not the Gremium.

Test: A backend test reads the board of a new team as a member and as a manager, and gets 404 as
a person outside the team.

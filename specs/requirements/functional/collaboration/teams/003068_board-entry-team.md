---
id: "003068"
title: A board entry names a team or a person
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/todos
  - backend/migrations
  - frontend/src/app/pages/todos
---

# A board entry names a team or a person

A member entry of a board must name a team or a person, never a Gremium. A team entry must
stand for the members of the team at the time of the read. The data migration must change each
Gremium entry into an entry of the inherent team of that Gremium. This replaces 001063 and the
Gremium entry of 001077.

Reason: The team decides the board access, and an inherent team holds the same persons as its
Gremium.

Test: A backend test adds a team entry to a free board, adds a member to the team and reads the
board as that member.

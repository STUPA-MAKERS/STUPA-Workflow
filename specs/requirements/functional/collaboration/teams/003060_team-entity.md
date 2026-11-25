---
id: "003060"
title: A team is a named group of persons
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
  - frontend/src/app/features/gremien
---

# A team is a named group of persons

A team must be a stored element with a name, an optional parent team and a list of members.
A person must be able to belong to any number of teams. A team must be able to have its own
Info text, board and Termine like a Gremium.

Reason: Work groups such as a Referat or a project group are not a Gremium. They have no votes
and no meetings, but they need a board, Termine and a list of members.

Test: A backend unit test creates a team, adds two members and reads them back.

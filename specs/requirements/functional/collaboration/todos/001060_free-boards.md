---
id: "001060"
title: A free board belongs to no single Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# A free board belongs to no single Gremium

There must be free boards beside the boards of a Gremium, the personal boards and the team
boards. A free board must have a name and a list of members. A member entry must be either a
Gremium or one person, and a free board can have any number of both. A free board can have no
Gremium at all.

Reason: Work that spans several Gremien, or a project group of single persons, has no board of
its own today.

Test: A backend test creates a free board with two Gremien and one person and reads it as a
member of each Gremium and as the person.

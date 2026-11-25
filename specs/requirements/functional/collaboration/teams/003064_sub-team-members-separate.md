---
id: "003064"
title: A sub-team does not add its members to the parent team
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
  - backend/app/modules/todos
---

# A sub-team does not add its members to the parent team

A member of a sub-team must not count as a member of the parent team. A member of the parent
team must not count as a member of the sub-team. A board or a Termin that needs both must name
both teams.

Reason: A Referat can hold persons who are not members of the Gremium. Their membership in the
Referat must not open the board of the Gremium.

Test: A backend test adds a person to a sub-team only and gets 404 for the board of the parent
team.

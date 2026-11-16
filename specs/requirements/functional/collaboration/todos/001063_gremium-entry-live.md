---
id: "001063"
title: A Gremium entry stands for the members of the Gremium at the time of the read
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

# A Gremium entry stands for the members of the Gremium at the time of the read

A Gremium entry of a free board must stand for the active members of the Gremium at the time of
the read, not at the time of the entry. Each active member must count, whatever the role in the
Gremium. A person who leaves the Gremium must lose the access at once, and a new member must get
it at once.

Reason: The memberships come from OIDC and change. The same rule holds for the Termine
(000717).

Test: A backend test adds a person to a Gremium of the board and reads the board as that
person, then removes the membership and gets 404.

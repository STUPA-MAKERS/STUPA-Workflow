---
id: "001063"
title: A Gremium entry stands for the members of the Gremium at the time of the read
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_the_roles_of_the_entries_and_the_live_gremium"
implementation:
  - backend/app/modules/todos/access.py
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

---
id: "001064"
title: Members with Verwalten and admins manage a free board
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

# Members with Verwalten and admins manage a free board

Only the persons with the role `Verwalten` on a free board and the admins must be able to change
its name, columns, labels, settings and member entries. The settings sheet of the board must have
the section `Mitglieder` (`Members`) with the member entries and their roles. The last entry with
`Verwalten` must not be removed or lowered, else the request must answer 409 `last_manager`.

Reason: Each free board needs a person who can maintain it, also when its creator leaves.

Test: A backend test removes the last entry with `Verwalten` and gets 409.

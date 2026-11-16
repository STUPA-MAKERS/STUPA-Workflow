---
id: "001062"
title: Each member entry of a free board has a role
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/pages/todos
  - frontend/src/app/features/todos
---

# Each member entry of a free board has a role

Each member entry of a free board must have one of three roles: `Lesen` (`Read`) reads the board,
`Bearbeiten` (`Edit`) also works on the cards, and `Verwalten` (`Manage`) also changes the name,
the columns, the labels, the settings and the members. A person who is covered by several entries
must get the highest role of them. A read without a role must answer 404, a card write with
`Lesen` must answer 403 `todo_write_required`, and a change of the settings without `Verwalten`
must answer 403 `todo_configure_required`.

Reason: A board for a whole Gremium often needs readers who must not change the cards.

Test: A backend test reads, writes and configures the board with each of the three roles.

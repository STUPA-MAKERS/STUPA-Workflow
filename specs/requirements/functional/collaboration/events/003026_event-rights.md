---
id: "003026"
title: The board of an Event gives its rights
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/events/access.py
scope:
  - backend/app/modules/events
  - frontend/src/app/pages/events
---

# The board of an Event gives its rights

Each Event must belong to one board that is not a personal board. A
person must read an Event when the person reads its board, and must write it when the person
writes its board, with the same rules as a card of that board (`todo.write`, `todo.all`, the
entries of the board). Writing is create, change, status and delete. The OAuth scopes of the
to-dos must give the same access to the Events. A person who writes an Event can move it to
another board that the person writes.

Reason: Today the rights of an Event are the rights of its board, and the Gremien and teams
already set them there. One set of rights for the work and for the Event keeps them the same.

Test: A backend unit test reads an Event as a reader of its board, gets 404 without access to
the board and 403 as a reader who tries to change it, and changes it as a writer of the board.

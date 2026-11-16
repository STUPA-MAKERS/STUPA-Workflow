---
id: "001068"
title: A manager archives a free board and only an admin deletes it
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

# A manager archives a free board and only an admin deletes it

A person with `Verwalten` must be able to archive a free board. An archived board must not show
in the board picker, in `Alle`, in `Meine To-Dos` or in the search, and must be read-only. A
person with `Verwalten` must be able to restore it from the list of archived boards. Only an admin
must be able to delete a free board, after an archive, and the delete must remove its cards with
their comments, files and links.

Reason: An archive keeps the work for later reference, and a delete cannot be undone.

Test: A backend test archives a board, writes a card and gets 409 `board_archived`, then deletes
the board as a manager and gets 403.

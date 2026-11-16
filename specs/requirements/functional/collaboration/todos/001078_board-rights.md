---
id: "001078"
title: Board rights depend on the board kind and its entries
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

# Board rights depend on the board kind and its entries

On a board of a Gremium, each active member of the Gremium must read and edit the cards, whatever
the role in the Gremium. A member whose Gremium role holds `todo.configure` must manage the board
(the role `Verwalten`). The other entries of the board (001077) must add their roles. A free board
must follow its entries (001062). A personal board must be only for its owner, without an admin
bypass. A team board must be for the holders of its permission.

Reason: Every member of a Gremium works on the tasks of the Gremium, and the managers of a Gremium
maintain its board.

Test: A backend test edits a card as a Gremium member without `todo.write` and changes the columns
as a member with `todo.configure`.

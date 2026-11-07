---
id: "000534"
title: The type of a card is chosen once
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# The type of a card is chosen once

A card must have exactly one type: `To-Do`, `Veranstaltung` or `Beschaffung`. The dialog for
a new card must have a `Typ` selection with these three types. The menu of a to-do card must
have `Umwandeln in …` with `Veranstaltung` and `Beschaffung`. This action must ask for a
confirmation with the text that it cannot be undone. A Veranstaltung or a Beschaffung must not
change its type. The menu of an Event must have `Folgeveranstaltung anlegen`.

Reason: The links, totals and decisions of a typed card belong to its type. Without the type data they lose their meaning. A switch with more than two segments does not fit on a phone.

Test: A backend unit test gets 409 when it changes the type of an Event or a Beschaffung.

---
id: "000439"
title: An Event is a card with event data
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# An Event is a card with event data

A card on a Gremium board or a team board can carry event data: start, end, place and
expected participants. Such a card is an Event. A card on a personal board must not carry
event data. The event data must be stored 1:1 to the card in `todo_card_event`.

Reason: A card already holds the description, the due date, the assignees, the checklist,
the comments and the links. An Event needs only its key data in addition.

Test: A backend unit test sets event data on a card of each board kind.

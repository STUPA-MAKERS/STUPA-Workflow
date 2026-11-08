---
id: "000553"
title: A card is put on the agenda from the card
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - frontend/src/app/features/todos
  - backend/app/modules/livevote
---

# A card is put on the agenda from the card

A card on the board of a Gremium must have the action `Auf Tagesordnung setzen` (`Add to
agenda`). The action must offer the planned meetings of the Gremium, the next meeting first. The
action must not show when the card is on an agenda, when the Gremium has no planned meeting or
when the person cannot edit the agenda.

Reason: The need for a TOP shows up on the card, so the card must not need a detour through the
meeting.

Test: A frontend unit test puts a card on the next meeting, and a backend test refuses a second
agenda item.

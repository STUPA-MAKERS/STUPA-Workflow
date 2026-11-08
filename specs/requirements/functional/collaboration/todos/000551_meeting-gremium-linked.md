---
id: "000551"
title: A meeting shows its linked cards and a Gremium its board
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
  - frontend/src/app/features/todos
---

# A meeting shows its linked cards and a Gremium its board

The meeting page must show the cards that link the meeting.

The detail of a Gremium must have a tab `To-Dos`. The tab must show the open cards of the board
of the Gremium, and it must link to that board. A card belongs to a Gremium because it is on the
board of the Gremium, not because of a link. The tab must show only to a person who reads that
board.

Reason: A card can link a meeting, so the meeting page must show the link back. The board of a
Gremium already holds the cards of the Gremium, so a second relation by link is not necessary.

Test: A frontend unit test shows a linked card on the meeting page and a card of the board in the
tab `To-Dos` of the Gremium detail.

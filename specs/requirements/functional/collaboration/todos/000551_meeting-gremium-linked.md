---
id: "000551"
title: A meeting shows its linked cards and a Gremium its board
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
  - frontend/src/app/features/gremien/gremium-todos/gremium-todos.component.ts
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.ts
scope:
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
  - frontend/src/app/features/todos
---

# A meeting shows its linked cards and a Gremium its board

The menu of the meeting page must have the item `To-Dos`. The item must open a sheet with the cards
that link the meeting, from the side on a wide screen and from the bottom on a phone. The head of
the sheet must have the actions `Verknüpfen` and `To-Do anlegen` as icon buttons. The agenda column
must not show these cards, because a long agenda pushes them out of sight.

The detail of a Gremium must have a tab `To-Dos`. The tab must show the open cards of the board
of the Gremium, and it must link to that board. A card belongs to a Gremium because it is on the
board of the Gremium, not because of a link. The tab must show only to a person who reads that
board.

Reason: A card can link a meeting, so the meeting page must show the link back. The board of a
Gremium already holds the cards of the Gremium, so a second relation by link is not necessary.

Test: A frontend unit test shows a linked card on the meeting page and a card of the board in the
tab `To-Dos` of the Gremium detail.

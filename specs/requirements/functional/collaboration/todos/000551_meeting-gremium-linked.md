---
id: "000551"
title: A meeting shows its links and a Gremium its board
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.html
  - frontend/src/app/features/gremien/gremium-todos/gremium-todos.component.ts
  - frontend/src/app/features/gremien/gremium-detail/gremium-detail.component.ts
scope:
  - frontend/src/app/features/meetings
  - frontend/src/app/features/gremien
  - frontend/src/app/features/todos
---

# A meeting shows its links and a Gremium its board

The menu of the meeting page must have the item `Verknüpft` with a link icon. The item must open
a sheet `Verknüpft` with every link of the meeting that the person reads, of any kind (spec
001407), from the side on a wide screen and from the bottom on a phone. The head of the sheet must
have the actions `Verknüpfen` and `To-Do anlegen` as icon buttons. When nothing is linked, the
sheet must show the empty state `Nichts mit dieser Sitzung verknüpft`. The agenda column must not
show these links, because a long agenda pushes them out of sight.

The sheet of the open item (spec ui-kit:001800) is `Verknüpft mit TOP`, so that the two entries of the
menu have different names.

The detail of a Gremium must have a tab `To-Dos`. The tab must show the open cards of the board
of the Gremium, and it must link to that board. A card belongs to a Gremium because it is on the
board of the Gremium, not because of a link. The tab must show only to a person who reads that
board.

Reason: Any element can link a meeting (spec 001400), so the meeting page must show every link
back, not only the cards. The name `To-Dos` was wrong for the other kinds. The board of a
Gremium already holds the cards of the Gremium, so a second relation by link is not necessary.

Test: A frontend unit test shows a linked card in the sheet `Verknüpft` of the meeting page and a card of the board in the
tab `To-Dos` of the Gremium detail.

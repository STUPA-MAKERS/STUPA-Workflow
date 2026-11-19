---
id: "001340"
title: A detail head is as far from the top as from the side
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/sheet-bar/sheet-bar.component.spec.ts:SheetBarComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/sheet-bar
  - frontend/src/app/features/gremien/gremium-detail
  - frontend/src/app/features/meetings/top-sheet
  - frontend/src/app/features/voting/vote-panel
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A detail head is as far from the top as from the side

In the head of a detail surface, the top of the first element must be as far from the top
edge of the surface as its text is from the side edge. For a text, the top is the top of
its capital letters. For a logo, the top is its top edge. The actions of the head stay
centred on the first line of the title.

This applies to every detail pane with a title bar (Antrag, Abstimmung, Ticket, Rechnung,
Buchung, Umbuchung, Haushalt, To-do card, Gremium), the TOP sheet of a meeting and the
vote card beside it. On a phone the title sits in the detail bar, so this rule does not
apply there.

Reason: The capitals of a detail title sat 36px below the top edge, and the text sat 32px
from the side. The head looked as if it had more room above than at the side.

Test: A unit test of the sheet bar reads its style and expects the top padding of a title
bar to be the side padding less the distance to the capitals (`--sheet-bar-inset`,
`--sheet-bar-cap`).

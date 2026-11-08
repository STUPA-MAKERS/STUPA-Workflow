---
id: "000551"
title: A meeting and a Gremium show their linked cards
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

# A meeting and a Gremium show their linked cards

The meeting page must show the cards that link the meeting in a section `Verknüpft`. The detail
of a Gremium must show the cards that link the Gremium in a section `Verknüpft`. The detail of a
Gremium must link to the board of the Gremium for a person who reads that board.

Reason: A card can link a meeting and a Gremium, so these pages must show the link back.

Test: A frontend unit test shows a linked card on the meeting page and on the Gremium detail.

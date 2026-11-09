---
id: "000573"
title: A link between two cards shows on both cards
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A link between two cards shows on both cards

A link from one card to another card must show in `Verknüpft` (`Linked`) of both cards. Each
card must list the cards that it links and the cards that link it, and each other card once,
also when a link goes in each direction. A person who may write a card must be able to remove
the link from either card. The removal must remove every link between the two cards. A card
that the person cannot read must not show.

Reason: A link connects two pieces of work. When it shows only on the card that made it, the
other card looks as if it had no link.

Test: A backend unit test links card A to card B and reads both cards. A frontend unit test
removes the link from card B.

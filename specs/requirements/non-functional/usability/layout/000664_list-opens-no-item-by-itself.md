---
id: "000664"
title: A list page opens no item by itself
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
tests:
  - "frontend/src/app/features/voting/voting-page/voting.component.spec.ts:VotingComponent"
  - "frontend/src/app/features/gremien/gremien-page/gremien.component.spec.ts:GremienComponent"
implementation:
  - frontend/src/app/features/voting
  - frontend/src/app/features/gremien
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A list page opens no item by itself

A list page with a detail pane must not open an item when the person opens the page without
an item in the address. The detail pane must show the empty state of 000665. This applies
also to Abstimmungen and Gremien. The budget page keeps its overview, because the overview is
not an item of the list.

Reason: Five of the eight list pages open nothing. An item that opens by itself can mark
something as read that the person did not choose.

Test: A unit test of the pages Abstimmungen and Gremien opens the list route with items and
expects no navigation to an item.

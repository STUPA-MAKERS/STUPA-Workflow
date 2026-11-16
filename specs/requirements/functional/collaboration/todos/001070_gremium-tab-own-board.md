---
id: "001070"
title: The To-Dos tab of a Gremium shows only the board of the Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
implementation: null
scope:
  - frontend/src/app/features/todos
  - frontend/src/app/features/gremien
---

# The To-Dos tab of a Gremium shows only the board of the Gremium

The tab `To-Dos` of a Gremium and its menu item `Board öffnen` must show only the board of that
Gremium, not the free boards that have the Gremium as a member entry.

Reason: The tab shows the work of the Gremium itself. A free board is found in the Boards tab
(001067).

Test: A frontend test shows the tab of a Gremium that is also on a free board and finds only the
cards of the Gremium board.

---
id: "002882"
title: A Bestellung stays editable in a closed Haushaltsjahr
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
---

# A Bestellung stays editable in a closed Haushaltsjahr

The close of a Haushaltsjahr must not lock the Bestellungen of its Anträge. A booking from such
a Bestellung must follow the rule of the closed year (F/finance/budget/000252).

Reason: A Bestellung moves no money (002857). A delivery can arrive after the close of the year.

Test: A backend integration test closes the year and sets a Bestellung to "Geliefert".

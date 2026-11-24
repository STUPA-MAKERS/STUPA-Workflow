---
id: "002870"
title: The row of a Bestellung has a menu with its actions
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
---

# The row of a Bestellung has a menu with its actions

For a person with `order.manage` the ⋮ menu of a row must have these entries in this order: "Als
bestellt markieren", "Als geliefert markieren", "Rechnung verknüpfen", "Rechnung anlegen",
"Buchung anlegen", "Bearbeiten", "Stornieren", "Löschen". The menu must leave out the entry of
the current status. "Rechnung anlegen" and "Buchung anlegen" must show only for a person with
`budget.book`. "Löschen" must ask before it deletes.

Reason: The usual steps of a purchase are one click each. An entry that the person cannot use
must not show.

Test: A frontend unit test opens the menu with and without `budget.book` and for a delivered
Bestellung and reads the entries.

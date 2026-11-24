---
id: "002870"
title: The detail of a Bestellung has its actions
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages
---

# The detail of a Bestellung has its actions

For a person with `order.manage` the detail of a Bestellung (002936) must have these actions in
this order: "Als bestellt markieren", "Als geliefert markieren", "Rechnung verknüpfen", "Rechnung
anlegen", "Buchung anlegen", "Bearbeiten", "Stornieren", "Löschen". The next status of the
Bestellung must be the main button, and the other actions must be in the ⋮ menu. The detail must
leave out the action of the current status. "Rechnung anlegen" and "Buchung anlegen" must show
only for a person with `budget.book`. "Löschen" must ask before it deletes.

Reason: The usual steps of a purchase are one click each. An action that the person cannot use
must not show.

Test: A frontend unit test opens the detail with and without `budget.book` and for a delivered
Bestellung and reads the actions.

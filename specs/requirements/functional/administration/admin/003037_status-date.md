---
id: "003037"
title: A status of a Bestellung can set a date
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/rules.py
scope:
  - backend/app/modules/statuses
  - backend/app/modules/orders
  - frontend/src/app/pages/admin
---

# A status of a Bestellung can set a date

A status of the list of the Bestellungen can have the setting `Setzt Datum` with the value
`Bestelldatum` or `Lieferdatum`. A change of a Bestellung to such a status must set this date
to the current day when the date is empty. A date that a person set must stay.

Reason: Today `Bestellt` and `Geliefert` set their dates (002853). A setting on the status keeps
this when an admin renames or adds a status.

Test: A backend unit test gives a new status the setting `Lieferdatum`, sets a Bestellung to it
and reads the delivery date of today, and keeps a typed date.

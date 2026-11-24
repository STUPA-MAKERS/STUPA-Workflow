---
id: "002893"
title: The anonymization of an Antrag keeps its Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/privacy
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# The anonymization of an Antrag keeps its Bestellungen

The anonymization of an Antrag must keep its Bestellungen. It must set `buyerName` to empty for
each of them.

Reason: A Bestellung is a record of the finances, like a booking, and must stay for the
Kassenprüfung. A typed buyer name is the only personal text in it.

Test: A backend integration test anonymizes an Antrag and reads its Bestellungen without the
buyer name.

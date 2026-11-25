---
id: "002850"
title: A Bestellung belongs to at most one Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/models.py
  - backend/app/modules/orders/service.py
scope:
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# A Bestellung belongs to at most one Antrag

A Bestellung can belong to one Antrag, and it can have none (003014). The person sets the Antrag
at the create. The Antrag of a Bestellung must not change after the create, and a Bestellung
without an Antrag must not get one later. An Antrag can have many Bestellungen. The delete of an
Antrag must delete its Bestellungen in the same transaction.

Reason: A Bestellung says what a person bought for an Antrag, and the Antrag gives it the
approved amount and the Kostenstelle to compare with. A purchase from the time before the
platform has no Antrag, and its bookings must still name it.

Test: A backend integration test creates two Bestellungen for one Antrag, refuses a change of
the Antrag, refuses an Antrag for a Bestellung without one and deletes the Antrag with its
Bestellungen.

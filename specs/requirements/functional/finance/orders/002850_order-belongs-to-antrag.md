---
id: "002850"
title: A Bestellung belongs to one Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/orders/models.py
  - backend/app/modules/orders/service.py
scope:
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# A Bestellung belongs to one Antrag

A Bestellung must belong to exactly one Antrag. The Antrag of a Bestellung must not change after
the create. An Antrag can have many Bestellungen. The delete of an Antrag must delete its
Bestellungen in the same transaction.

Reason: A Bestellung says what a person bought for an Antrag. Without the Antrag it has no
approved amount and no Kostenstelle to compare with.

Test: A backend integration test creates two Bestellungen for one Antrag, refuses a change of
the Antrag and deletes the Antrag with its Bestellungen.

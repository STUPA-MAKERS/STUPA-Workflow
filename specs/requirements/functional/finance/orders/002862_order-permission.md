---
id: "002862"
title: The write of a Bestellung needs order.manage
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
  - backend/app/shared
---

# The write of a Bestellung needs order.manage

The create, the change, the status change and the delete of a Bestellung must need the
permission `order.manage`. The permission must be in the role matrix with the name "Bestellungen
verwalten". No other permission must give the write of a Bestellung.

Reason: The persons who order are not always the persons who work on an Antrag or who book. An
own permission lets a role order without the right to book.

Test: A backend test per write route answers 403 for a person with `application.manage` and
`budget.book` and without `order.manage`.

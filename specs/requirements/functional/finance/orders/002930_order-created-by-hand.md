---
id: "002930"
title: Only a person creates a Bestellung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
  - backend/app/modules/flow
---

# Only a person creates a Bestellung

Only the request of a person who holds `order.manage` must create a Bestellung. The platform
must not create a Bestellung from a flow action, a cron, an import, a booking, an invoice or a
to-do card. A migration must not create a Bestellung from older data.

Reason: A Bestellung says that a person bought something. A Bestellung that the platform
creates by itself says that for a purchase that nobody made.

Test: A backend unit test fires every flow action on an approved Antrag and reads no
Bestellung. A test of the migration reads an empty table.

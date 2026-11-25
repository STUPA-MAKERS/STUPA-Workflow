---
id: "003016"
title: The export of finance data needs finance.export
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/shared/permissions.py
  - backend/app/modules/budget/tree_router.py
  - backend/app/modules/orders/list_router.py
scope:
  - backend/app/modules/budget
  - backend/app/modules/orders
  - backend/app/modules/auth
  - backend/app/shared
  - backend/migrations
---

# The export of finance data needs finance.export

One permission must give every file export of the finance pages: the Haushalt, the bookings
and the Bestellungen (F/finance/orders/002886). Its key must be `finance.export` and its name
in the role matrix must be "Finanzen exportieren". It replaces the key `budget.export`. A
migration must change the key in every role, so that each role that had `budget.export` has
`finance.export` and no other role gets it. An OAuth scope that carried `budget.export` must
carry `finance.export`. The platform must know the key `budget.export` no more.

Reason: The right now covers more than the Haushalt, and a name that says "Haushalt" would
hide that it also takes the Bestellungen out of the platform. One key with the right name
keeps the role matrix true.

Test: A migration test gives a role `budget.export`, runs the migration and reads
`finance.export` and no `budget.export`. A backend test per export route answers 403 without
`finance.export`. A unit test of the permission list finds no `budget.export`.

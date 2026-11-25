---
id: "002886"
title: The list of Bestellungen exports as XLSX
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/list_router.py
scope:
  - backend/app/modules/orders
---

# The list of Bestellungen exports as XLSX

`GET /api/orders/export.xlsx` must give the Bestellungen of the current filter as an XLSX file
with the amounts as numbers. The export must need `finance.export`
(F/finance/budget/003016). The file must hold only the Bestellungen that the person reads
(002863). `order.manage` alone must not export. It must
write an audit entry.

Reason: The Kassenprüfung compares the purchases with the bookings outside the platform. One
export right for the bookings and the Bestellungen means that one role decides who takes
finance data out of the platform.

Test: A backend integration test exports with a filter and reads the rows. It gets 403 with
`order.manage` and without `finance.export`.

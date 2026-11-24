---
id: "002886"
title: The list of Bestellungen exports as XLSX
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
---

# The list of Bestellungen exports as XLSX

`GET /api/orders/export.xlsx` must give the Bestellungen of the current filter as an XLSX file
with the amounts as numbers. The export must need `order.manage`. It must write an audit entry.

Reason: The Kassenprüfung compares the purchases with the bookings outside the platform. The
person who manages the Bestellungen already reads every row of the export.

Test: A backend integration test exports with a filter, reads the rows and gets 403 without
`order.manage`.

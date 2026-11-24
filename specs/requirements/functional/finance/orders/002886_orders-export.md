---
id: "002886"
title: The list of Bestellungen exports as XLSX
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
---

# The list of Bestellungen exports as XLSX

`GET /api/orders/export.xlsx` must give the Bestellungen of the current filter as an XLSX file
with the amounts as numbers. The export must need `budget.export`. It must write an audit entry.

Reason: The Kassenprüfung compares the purchases with the bookings outside the platform. The
other finance exports need the same permission.

Test: A backend integration test exports with a filter, reads the rows and gets 403 without
`budget.export`.

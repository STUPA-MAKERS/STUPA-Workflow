---
id: "000262"
title: The invoice list has three segments
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/pages/invoices/invoices.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# The invoice list has three segments

The invoice list must show "Eingang" (open, no booking), "Verbucht" (open, with a booking) and
"Bezahlt". Each segment must show its count under the other filters.

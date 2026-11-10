---
id: "000262"
title: The invoice list has four segments
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/src/app/pages/invoices/invoices.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# The invoice list has four segments

The invoice list must have the segments "Alle", "Eingang" (open, no booking), "Verbucht"
(open, with a booking) and "Bezahlt". A segment must show only its name (000560).

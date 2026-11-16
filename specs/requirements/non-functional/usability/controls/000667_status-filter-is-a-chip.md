---
id: "000667"
title: A list filters the status with a chip
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/pages/invoices/invoices.component.spec.ts:InvoicesComponent"
implementation:
  - frontend/src/app/pages/invoices
  - frontend/src/app/pages/invoices/invoices.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A list filters the status with a chip

A list page must filter by status with a filter chip that has the name "Status". The chip
must be the first chip. The invoices page must not use a segmented control for the status. Its
chip must have the values "Eingang" (open, no booking), "Verbucht" (open, with a booking)
and "Bezahlt".

Reason: Anträge, Tickets and Abstimmungen use the chip. Rechnungen follows the pattern of
Anträge (000417), and the list head is one row lower without the segmented control.

Test: A unit test of the invoices page expects a status chip and no segmented control in the
list head.

---
id: "000145"
title: A reverted booking keeps the invoice status
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-06
replaced_by: F/finance/invoices/000261
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A reverted booking keeps the invoice status

The revert of a booking does not change the status of its invoice.

Reason: A booking never sets the invoice status.

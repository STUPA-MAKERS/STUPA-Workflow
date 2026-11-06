---
id: "000261"
title: Only a user sets an invoice to paid
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/invoices.py
  - frontend/src/app/pages/invoices/invoice-detail/invoice-detail.component.ts
scope:
  - backend/app/modules/budget
---

# Only a user sets an invoice to paid

A booking must not change the status of its invoice. The invoice must stay open until a user
sets "Als bezahlt markieren".

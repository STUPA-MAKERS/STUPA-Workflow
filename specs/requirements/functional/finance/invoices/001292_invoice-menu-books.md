---
id: "001292"
title: The head menu of an invoice has "Buchung anlegen"
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/pages/invoices/invoice-detail/invoice-detail.component.spec.ts:InvoiceDetailComponent"
implementation:
  - frontend/src/app/pages/invoices/invoice-detail/invoice-detail.component.ts
scope:
  - frontend/src/app/pages/invoices
---

# The head menu of an invoice has "Buchung anlegen"

The ⋮ menu in the head of the invoice detail must have the entry "Buchung anlegen" for a person
who books. The entry must open the dialog "Neue Buchung" with this invoice preselected, like the
entry in the row menu of the invoice list. This entry is an exception to 000671.

Reason: On a phone the section "Buchungen" is far below the head. The person looks for the
action in the menu of the invoice.

Test: A unit test of the invoice detail picks the menu entry and expects the create event.

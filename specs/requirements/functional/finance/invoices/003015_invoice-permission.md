---
id: "003015"
title: The write of an invoice needs invoice.manage or budget.book
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/shared/permissions.py
  - backend/app/modules/budget/tree_router.py
scope:
  - backend/app/modules/budget
  - backend/app/shared
  - frontend/src/app/pages
---

# The write of an invoice needs invoice.manage or budget.book

The create, the change, the delete and the file upload of an invoice, the ZUGFeRD import
included, must need the permission `invoice.manage` or the permission `budget.book`. The
permission `invoice.manage` must be in the role matrix with the name "Rechnungen verwalten". It
must give no read: the read of the invoices keeps its own permissions. It must give no booking,
so "Buchung anlegen" of an invoice still needs `budget.book`. The platform must give
`invoice.manage` to no role on its own.

Reason: The person who collects and enters the invoices is not always the person who books. An
own permission lets a role keep the invoices without the right to move money. `budget.book`
keeps the write, so no role of today loses a right.

Test: A backend test per write route of the invoices accepts a person with `invoice.manage` and
without `budget.book`, accepts a person with `budget.book` alone and answers 403 without both.
A backend test refuses the create of a booking with `invoice.manage` alone. A frontend unit
test shows the invoice actions with `invoice.manage` and hides "Buchung anlegen".

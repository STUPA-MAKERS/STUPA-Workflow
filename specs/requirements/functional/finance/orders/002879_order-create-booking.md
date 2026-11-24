---
id: "002879"
title: Buchung anlegen fills the booking form from the Bestellung
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/pages/applications/orders/orders-section.component.ts
  - frontend/src/app/pages/expenses/expense-dialogs.state.ts
scope:
  - frontend/src/app/pages/applications
  - frontend/src/app/pages/expenses
---

# Buchung anlegen fills the booking form from the Bestellung

The entry "Buchung anlegen" of a Bestellung must open the dialog "Neue Buchung" with these
values: the Bestellung, its Antrag, the Kostenstelle and the Haushaltsjahr of the Antrag, the
invoice, the Bezeichnung as the description and the Händler as the Empfänger. The amount must be
the real price, else the planned price, minus the amounts already booked for the Bestellung, and
at least 0. For an Auslage the Empfänger must be the buyer. The person must be able to change
each value.

Reason: Every value is already known at the Bestellung. A copy by hand takes time and makes
errors. The booking itself follows its own rules, for example F/finance/budget/000629 and
F/finance/invoices/001290.

Test: A frontend unit test opens the dialog from a Bestellung with one booking and reads each
prefilled value and the rest amount.

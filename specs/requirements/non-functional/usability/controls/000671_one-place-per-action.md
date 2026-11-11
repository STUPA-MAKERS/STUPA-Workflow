---
id: "000671"
title: A view shows an action in one place
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/pages/invoices
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A view shows an action in one place

A view must not show the same action two times. An action that belongs to a section must
stand in the head of that section. The invoice detail must show "Buchung anlegen" only in the
head of the section "Buchungen".

Reason: The invoice detail shows "Buchung anlegen" below the title and again in the section.
The person cannot tell if the two buttons do the same.

Test: A unit test of the invoice detail expects exactly one button "Buchung anlegen".

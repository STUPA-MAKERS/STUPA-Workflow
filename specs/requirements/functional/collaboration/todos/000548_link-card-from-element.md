---
id: "000548"
title: An element is linked to a card from its detail
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - frontend/src/app/features/todos
  - frontend/src/app/pages/applications
  - frontend/src/app/features/voting
  - frontend/src/app/pages/invoices
  - frontend/src/app/pages/expenses
---

# An element is linked to a card from its detail

The section `Verknüpft` of an Antrag, a vote, an invoice and a Buchung must have the action
`Verknüpfen` (`Link`). The action must open a search over the cards that the person writes. A
picked card must get a link to the element under the link rules of the card. The search must not
offer a card that already links the element.

Reason: A card often exists before its Antrag or its Buchung.

Test: A frontend unit test links a card from a Buchung and checks the new row in `Verknüpft`.

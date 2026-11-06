---
id: "000489"
title: The cards of an element are under Verknüpft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/features/todos
  - frontend/src/app/pages/applications
  - frontend/src/app/pages/expenses
---

# The cards of an element are under Verknüpft

The detail of an Antrag, a Buchung or an invoice must show its cards in the section
`Verknüpft` (`Linked`). A Buchung must show them in its existing section `Verknüpft`. A linked
Event must be the first row and show its dates, its board, its place and its balance. The
detail must not show the Event in its details.

Reason: An Event is the most important link of an element. One section for all links keeps the
detail short.

Test: A frontend unit test checks that a linked Event is the first row.

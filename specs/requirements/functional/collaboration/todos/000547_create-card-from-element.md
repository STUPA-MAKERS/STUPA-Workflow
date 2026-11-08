---
id: "000547"
title: A card is created from the detail of an element
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

# A card is created from the detail of an element

The detail of an Antrag, a vote, an invoice and a Buchung must have the action `To-Do anlegen`
(`Add to-do`) in its section `Verknüpft`. The action must open the create dialog of the agenda
item with a link to the element. The dialog must preselect the board of the Gremium of the
element when the person writes that board. The section must show the action also when no card
is linked. The action must not show for a person who writes no board.

Reason: The work on an element starts on its detail. A detour through the board loses the link.

Test: A frontend unit test opens the dialog from an Antrag and checks the link and the board.

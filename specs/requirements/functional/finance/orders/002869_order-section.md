---
id: "002869"
title: The Antrag lists its Bestellungen under Verknüpft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/pages/applications/applications-detail.component.ts
  - frontend/src/app/features/todos/linked-list/todo-linked-list.component.ts
scope:
  - frontend/src/app/pages/applications
  - frontend/src/app/features/todos
---

# The Antrag lists its Bestellungen under Verknüpft

The detail of an Antrag must show each Bestellung of the Antrag as a row of the list
"Verknüpft", like a linked element. The row must show the Bezeichnung, the status and the price,
and it must open the Bestellung on the page "Bestellungen" (002883). The detail of an Antrag must
not have a section "Bestellungen" and must not open a dialog for a Bestellung. For a person with
`order.manage` the head of "Verknüpft" of an approved Antrag of a type with money must have the
action "Bestellung anlegen", which opens the form on the page "Bestellungen" with this Antrag.
In the applicant view the row must show the values of 002864 and must not be a link.

Reason: A section with a dialog inside the Antrag hides the Bestellungen and is slow to work
with. The page "Bestellungen" is the place of the work, and the Antrag only points to it, like
to every other linked element.

Test: A frontend unit test renders an Antrag with two Bestellungen, reads the two rows under
"Verknüpft" with their link to the page and finds no section "Bestellungen".

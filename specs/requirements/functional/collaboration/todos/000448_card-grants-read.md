---
id: "000448"
title: A card gives read access to its links
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/applications
  - backend/app/modules/budget
  - backend/app/modules/livevote
  - backend/app/modules/voting
  - backend/app/modules/tickets
---

# A card gives read access to its links

Each person who can read a card must be able to read the elements that the card links: Anträge,
Buchungen, invoices, decisions, meetings, TOPs, votes, tickets and other cards. This access is
read only. This access must not show the PII fields of an Antrag or the data of a ticket
reporter. This access must not continue to the links of a linked card. A person must be able
to link only an element that the person can read.

Reason: The people who work on a card need all of its documents, also from Kostenstellen and
Gremien that they cannot read otherwise. The link check stops a person from sharing an element
that the person cannot read.

Test: A backend unit test reads a linked Buchung as a board reader without `budget.read`.

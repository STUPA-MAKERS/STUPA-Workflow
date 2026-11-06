---
id: "000448"
title: An Event gives read access to its links
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
---

# An Event gives read access to its links

Each person who can read an Event must be able to read its linked Anträge, Buchungen,
invoices, decisions, TOPs and votes. This access is read only. This access must not show the
PII fields of an Antrag. A person must be able to link only an element that the person can
read. The rule "A link shows nothing without access" does not apply to the links of an Event.

Reason: The people who plan an Event need all of its documents, also from Kostenstellen and
Gremien that they cannot read otherwise. The link check stops a person from sharing an element
that the person cannot read.

Test: A backend unit test reads a linked Buchung as a board reader without `budget.read`.

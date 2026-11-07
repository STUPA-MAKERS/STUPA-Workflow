---
id: "000537"
title: An Antrag, an invoice or a Buchung belongs to at most one Beschaffung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# An Antrag, an invoice or a Buchung belongs to at most one Beschaffung

An Antrag, an invoice or a Buchung must be linked to at most one Beschaffung. The same element
can also be linked to one Event. To split a Buchung across Beschaffungen, link each sub-booking
to its Beschaffung.

Reason: With one Beschaffung per element, the sum of all Beschaffung totals is never more than the budget total. A purchase for an Event belongs to both.

Test: A backend unit test gets 409 for a second Beschaffung link to the same Buchung.

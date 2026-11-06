---
id: "000481"
title: An Antrag or a Buchung belongs to at most one Event
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# An Antrag or a Buchung belongs to at most one Event

An Antrag, a Buchung or an invoice must be linked to at most one Event. To split a Buchung
across Events, link each sub-booking to its Event.

Reason: With one Event per element, the sum of all Event totals is never more than the
budget total.

Test: A backend unit test gets 409 for a second Event link to the same Buchung.

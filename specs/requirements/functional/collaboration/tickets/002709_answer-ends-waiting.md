---
id: "002709"
title: An answer of the sender ends Wartet auf Antwort
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_message_of_the_sender_sets_in_progress_without_an_actor"
implementation:
  - backend/app/modules/tickets/service.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# An answer of the sender ends Wartet auf Antwort

A message of the sender on a ticket with the status `Wartet auf Antwort` must set the status `In
Bearbeitung` and write a status event without a person.

Reason: The team must see without a look into each ticket that the answer is there.

Test: A unit test adds a sender message to a waiting ticket and expects `In Bearbeitung`.

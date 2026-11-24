---
id: "002710"
title: An answer on a closed ticket opens it again for 14 days
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_late_answer_opens_a_follow_up_ticket_in_the_same_bereich"
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_an_answer_in_time_or_on_an_open_ticket_is_no_follow_up"
  - "backend/tests/unit/modules/tickets/test_ticket_router.py:test_a_late_message_of_the_reporter_becomes_a_new_ticket"
implementation:
  - backend/app/modules/tickets/models.py
  - backend/app/modules/tickets/service/reporter.py
  - backend/app/modules/tickets/router.py
  - frontend/src/app/pages/tickets/ticket-detail.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# An answer on a closed ticket opens it again for 14 days

A message of the sender on a ticket with the status `Erledigt` or `Abgelehnt` must set the
status `In Bearbeitung` when the close is at most 14 days old. After that time, and on an
anonymized ticket, the message must become a new ticket in the same Bereich that names the old
ticket.

Reason: A fast answer belongs to the same case. A late answer is mostly a new case, and an
anonymized ticket has no sender to whom the message can belong (002716).

Test: A unit test answers a ticket 15 days after the close and expects a new ticket with a
reference to the old one.

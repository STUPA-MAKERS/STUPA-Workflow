---
id: "002732"
title: An automatic mail opens no ticket
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_an_automatic_answer_is_an_event_and_no_message"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_an_automatic_mail_without_a_ticket_stays_in_the_inbox"
  - "backend/tests/unit/modules/tickets/test_ticket_mail_parse.py:test_a_mail_of_a_machine_is_automatic"
implementation:
  - backend/app/modules/tickets/mail_import.py
  - backend/app/modules/tickets/mail_parse.py
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# An automatic mail opens no ticket

A mail with the header `Auto-Submitted` other than `no`, with `Precedence` `bulk`, `list` or
`junk`, or with an empty return path must not become a new ticket and must get no confirmation
(002738). When it belongs to a ticket (002726), it must become an event of that ticket that the
team sees. In each other case it must stay in the inbox.

Reason: An out-of-office answer and a bounce are not a case. An answer to them starts a loop
between two machines.

Test: A unit test imports an out-of-office answer to a sent mail and expects an event, no
message and no mail.

---
id: "002725"
title: A new mail becomes a ticket
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_a_new_mail_becomes_a_ticket_with_the_values_of_the_mail"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_a_mail_without_a_subject_gets_the_title_ohne_betreff"
implementation:
  - backend/app/modules/tickets/mail_import.py
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# A new mail becomes a ticket

A mail that belongs to no ticket (002726, 002727) must become a new ticket in the Bereich of the
Postfach, with the source mail, the status `Neu`, the subject as title, the text as first
message and the address and the name of `From` as sender. A mail without a subject must get the
title `Ohne Betreff`.

Reason: The Postfach is the helpdesk of the Bereich, so each mail must show as work.

Test: A unit test fetches a new mail and expects a ticket with these values.

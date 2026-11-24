---
id: "002726"
title: An answer joins its ticket through the mail headers
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_an_answer_joins_its_ticket_through_the_headers"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_the_newest_ticket_wins_with_more_than_one_hit"
implementation:
  - backend/app/modules/tickets/mail_import.py
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# An answer joins its ticket through the mail headers

A mail must become a message of a ticket when its `In-Reply-To` or its `References` names a
`Message-ID` that the platform stored for a mail of that ticket in the same Postfach. With more
than one hit the newest ticket must win.

Reason: The headers are the standard thread of a mail and stay when a person changes the
subject.

Test: A unit test fetches an answer with a known `In-Reply-To` and a different subject and
expects the message on the ticket.

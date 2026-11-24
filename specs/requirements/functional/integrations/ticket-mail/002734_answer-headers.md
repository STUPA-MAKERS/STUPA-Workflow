---
id: "002734"
title: A sent mail carries the thread headers and the number
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_send.py:test_a_sent_mail_carries_the_thread_headers_and_the_number"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_send.py:test_an_answer_to_a_sent_mail_comes_back_to_the_ticket"
implementation:
  - backend/app/modules/tickets/mail_send.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A sent mail carries the thread headers and the number

Each sent mail of a ticket must have its own `Message-ID`, which the platform stores. It must
name the last mail of the ticket in `In-Reply-To` and all mails of the ticket in `References`.
Its subject must be the title of the ticket with the number in the form `[T-7K3QX9MD]` at the
end, and with `Re:` at the start when it answers a mail.

Reason: The headers keep the thread in the mail program of the sender and bring the answer back
to the ticket (002726, 002727).

Test: A unit test sends two answers and expects the first `Message-ID` in the `References` of
the second.

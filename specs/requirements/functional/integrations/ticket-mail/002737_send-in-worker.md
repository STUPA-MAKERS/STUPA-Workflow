---
id: "002737"
title: The worker sends a mail and shows a failure on the message
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_send.py:test_eight_failed_sends_end_in_failed_and_resend_starts_again"
  - "frontend/src/app/pages/tickets/ticket-detail.component.spec.ts:TicketDetailComponent"
implementation:
  - backend/app/modules/tickets/mail_send.py
  - backend/worker/ticket_mail.py
  - backend/app/modules/tickets/router.py
  - frontend/src/app/pages/tickets/tickets.util.ts
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# The worker sends a mail and shows a failure on the message

The platform must send the mail of a message in a job of the worker, at most 8 times with a
longer wait after each failure. The message must show its state: `Wird gesendet`, `Gesendet` or
`Nicht gesendet`. A message with `Nicht gesendet` must have the action `Erneut senden`.

Reason: An outage of the mail server must not lose an answer, and the team must see that the
sender did not get it.

Test: A unit test lets the SMTP client fail eight times and expects `Nicht gesendet`.

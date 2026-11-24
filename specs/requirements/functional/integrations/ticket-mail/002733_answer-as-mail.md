---
id: "002733"
title: A public message on a mail ticket goes out as a mail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_send.py:test_a_public_message_goes_out_as_a_mail_and_an_internal_one_never"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_send.py:test_a_file_of_the_message_goes_with_the_mail_after_a_clean_scan"
  - "frontend/src/app/pages/tickets/ticket-detail.component.spec.ts:TicketDetailComponent"
implementation:
  - backend/app/modules/tickets/mail_send.py
  - backend/app/modules/tickets/service/notes.py
  - frontend/src/app/pages/tickets/ticket-detail.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A public message on a mail ticket goes out as a mail

A public message of the team on a ticket whose sender is an e-mail address must go out as a mail
through the SMTP account of the Postfach of the Bereich, with the full text and the files of the
message. An internal message must never go out.

Reason: The sender of a mail has no account and no view in the app, so the mail is the answer.

Test: A unit test writes one public and one internal message and expects one mail with the text
of the public one.

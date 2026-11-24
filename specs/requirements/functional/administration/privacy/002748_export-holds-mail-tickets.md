---
id: "002748"
title: The data export holds the mail tickets of the addresses of the person
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/privacy/test_privacy_ticket_mails.py:test_the_export_holds_the_mail_ticket_without_the_internal_message"
implementation:
  - backend/app/modules/tickets/privacy.py
  - backend/app/modules/privacy/service.py
scope:
  - backend/app/modules/privacy
  - backend/app/modules/tickets
---

# The data export holds the mail tickets of the addresses of the person

The data export of a person (000458) must hold each ticket whose sender or `Cc` address is an
address of that person, with the public messages and the names of the files. It must not hold
internal messages.

Reason: The right of access covers the mails that a person wrote to a Postfach of the platform.

Test: A unit test exports a person with one mail ticket and expects the ticket without its
internal message.

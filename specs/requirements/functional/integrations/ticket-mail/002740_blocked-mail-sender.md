---
id: "002740"
title: The mail of a blocked sender becomes no ticket
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_the_mail_of_a_blocked_sender_becomes_no_ticket"
implementation:
  - backend/app/modules/tickets/mail_import.py
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# The mail of a blocked sender becomes no ticket

The sender block (000315) must hold for mails. A mail from a blocked address, or from the
address of a blocked account, must make no ticket, no message and no confirmation. The block
must count the mail, and the mail must move to the folder for done mails (002731).

Reason: The team blocks a sender to stop the work that the sender makes, on each way into the
platform.

Test: A unit test imports a mail of a blocked address and expects no ticket and one hit.

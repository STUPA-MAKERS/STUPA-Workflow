---
id: "002744"
title: The hosts of a Postfach need the deploy settings
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_a_host_outside_the_allowlist_is_422"
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_an_empty_allowlist_refuses_each_host"
implementation:
  - backend/app/modules/tickets/mailbox.py
  - backend/app/settings.py
scope:
  - backend/app/
---

# The hosts of a Postfach need the deploy settings

The deploy setting `TICKET_MAIL_HOST_ALLOWLIST` names the hosts that the IMAP host and the SMTP
host of a Postfach can have. The save of a different host must answer 422
`mail_host_not_allowed`. With an empty list the save must refuse each host.

Reason: A host that an admin sets freely lets the server open a connection to each internal host
(002514).

Test: A unit test saves a Postfach whose IMAP host is not in the list and expects 422.

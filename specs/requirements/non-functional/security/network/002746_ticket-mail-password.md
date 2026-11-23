---
id: "002746"
title: No read returns the password of a Postfach
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_create_stores_the_postfach_and_returns_no_password"
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_a_failure_is_a_short_cause_without_a_text_of_the_server"
implementation:
  - backend/app/modules/tickets/mailbox_schemas.py
  - backend/app/modules/tickets/mailbox.py
  - backend/app/modules/tickets/mail_client.py
scope:
  - backend/app/
---

# No read returns the password of a Postfach

The platform must log in to a Postfach with a user name and a password. A read of a Postfach
must not return a password and must say only that one is set. A log line, an audit entry and an
error text must not hold a password.

Reason: A password is enough for each mail server that has app passwords, and the mail server of
the operator is the first one. A read that returns it gives the mail account to each person who
can open the page (002515).

Test: A unit test reads a saved Postfach and expects no password in the answer.

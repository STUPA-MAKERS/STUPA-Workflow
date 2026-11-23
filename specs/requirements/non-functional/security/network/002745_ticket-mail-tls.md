---
id: "002745"
title: The platform talks to a mail server only through TLS
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_a_server_without_starttls_ends_before_the_login"
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_imap_uses_tls_from_the_start_or_starttls_before_the_login"
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_smtp_uses_tls_from_the_start_or_starttls_before_the_login"
implementation:
  - backend/app/modules/tickets/mail_client.py
scope:
  - backend/app/
---

# The platform talks to a mail server only through TLS

Each connection to the IMAP account and to the SMTP account of a Postfach must use TLS from the
start or STARTTLS before the login, with a checked certificate. When the server offers no TLS,
the platform must end the connection before it sends the password.

Reason: The connection carries the password of the account and the mails of persons.

Test: A unit test connects to a server without STARTTLS and expects an error before the login.

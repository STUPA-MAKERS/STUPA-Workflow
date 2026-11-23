---
id: "002745"
title: The platform talks to a mail server only through TLS
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
---

# The platform talks to a mail server only through TLS

Each connection to the IMAP account and to the SMTP account of a Postfach must use TLS from the
start or STARTTLS before the login, with a checked certificate. When the server offers no TLS,
the platform must end the connection before it sends the password.

Reason: The connection carries the password of the account and the mails of persons.

Test: A unit test connects to a server without STARTTLS and expects an error before the login.

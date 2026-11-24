---
id: "002515"
title: The Paperless token never leaves the server
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/paperless/test_paperless.py:test_the_connection_saves_and_no_read_returns_the_token"
  - "backend/tests/unit/modules/paperless/test_rules.py:test_no_oauth_scope_carries_a_paperless_permission"
implementation:
  - backend/app/modules/paperless/schemas.py
  - backend/app/modules/paperless/connection.py
scope:
  - backend/app/
---

# The Paperless token never leaves the server

The API must not return the token of the Paperless connection. A log line, an audit entry and
an error text must not contain it. The read of the connection must tell only if a token is set.

Reason: The token gives access to each document that the account of the platform reads.

Test: A unit test reads the connection and expects no token in the answer.

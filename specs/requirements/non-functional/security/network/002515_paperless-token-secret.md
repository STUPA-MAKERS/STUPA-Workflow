---
id: "002515"
title: The Paperless token never leaves the server
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
---

# The Paperless token never leaves the server

The API must not return the token of the Paperless connection. A log line, an audit entry and
an error text must not contain it. The read of the connection must tell only if a token is set.

Reason: The token gives access to each document that the account of the platform reads.

Test: A unit test reads the connection and expects no token in the answer.

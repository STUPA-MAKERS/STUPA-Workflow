---
id: "002513"
title: Each call to Paperless uses the token of the connection
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/paperless/test_client.py:test_each_request_carries_the_token_and_none_deletes"
implementation:
  - backend/app/modules/paperless/client.py
scope:
  - backend/app/
  - frontend/src/app/
---

# Each call to Paperless uses the token of the connection

The platform must make each call to Paperless with the token of the connection. The platform
must not hold a Paperless token of a person.

Reason: One account in Paperless holds the rights of the platform. The permission
`paperless.use` decides who uses that account (002524).

Test: A unit test of the client expects the token of the connection in each request.

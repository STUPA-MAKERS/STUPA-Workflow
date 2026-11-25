---
id: "003101"
title: The pretix and Mollie tokens never leave the server
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The pretix and Mollie tokens never leave the server

The API must not return the token of the pretix connection or of the Mollie connection. A log
line, an audit entry and an error text must not contain them. The read of a connection must
tell only if a token is set. The tokens must be sealed like each secret (002810).

Reason: The pretix token gives access to the orders and the guests, and the Mollie token to the
payments of the student government.

Test: A backend unit test reads both connections and expects no token in the answer.

---
id: "002737"
title: The worker sends a mail and shows a failure on the message
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# The worker sends a mail and shows a failure on the message

The platform must send the mail of a message in a job of the worker, at most 8 times with a
longer wait after each failure. The message must show its state: `Wird gesendet`, `Gesendet` or
`Nicht gesendet`. A message with `Nicht gesendet` must have the action `Erneut senden`.

Reason: An outage of the mail server must not lose an answer, and the team must see that the
sender did not get it.

Test: A unit test lets the SMTP client fail eight times and expects `Nicht gesendet`.

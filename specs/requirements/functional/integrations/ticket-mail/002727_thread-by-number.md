---
id: "002727"
title: The number in the subject joins only a mail of a participant
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# The number in the subject joins only a mail of a participant

A mail without a known header (002726) must become a message of a ticket when its subject holds
the number of a ticket of the same Postfach in the form `[T-7K3QX9MD]`, and its `From` address
is the sender or a `Cc` address of that ticket. From a different address the mail must become a
new ticket.

Reason: Some mail programs drop the headers. Without the address check each person who knows a
number could write into the ticket of a different person.

Test: A unit test sends `[T-7K3QX9MD]` from an unknown address and expects a new ticket.

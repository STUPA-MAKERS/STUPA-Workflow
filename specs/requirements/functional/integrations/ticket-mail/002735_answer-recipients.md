---
id: "002735"
title: An answer goes to the sender and to the Cc addresses of the thread
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# An answer goes to the sender and to the Cc addresses of the thread

The form for a public message on a mail ticket must show the recipients: the sender in `An` and
each `Cc` address of the mails of the ticket in `Cc`, without the address of the Postfach. The
writer must be able to remove and to add addresses before the send.

Reason: A mail with `Cc` is a talk of more than two persons. The team must see to whom a text
goes and must be able to keep an address out.

Test: A unit test answers a mail with one `Cc` address and expects the address in `Cc` of the
sent mail.

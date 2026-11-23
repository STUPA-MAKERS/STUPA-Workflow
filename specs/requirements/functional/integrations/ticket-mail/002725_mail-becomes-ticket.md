---
id: "002725"
title: A new mail becomes a ticket
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# A new mail becomes a ticket

A mail that belongs to no ticket (002726, 002727) must become a new ticket in the Bereich of the
Postfach, with the source mail, the status `Neu`, the subject as title, the text as first
message and the address and the name of `From` as sender. A mail without a subject must get the
title `Ohne Betreff`.

Reason: The Postfach is the helpdesk of the Bereich, so each mail must show as work.

Test: A unit test fetches a new mail and expects a ticket with these values.

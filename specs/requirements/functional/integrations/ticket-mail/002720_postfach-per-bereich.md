---
id: "002720"
title: A Bereich has at most one Postfach
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/help-tickets
---

# A Bereich has at most one Postfach

A Bereich must be able to hold one Postfach: an e-mail address with an IMAP account and an SMTP
account. A Postfach must belong to exactly one Bereich. The Bereich `Plattform` must be able to
hold a Postfach like each other Bereich.

Reason: One address for each Bereich makes the sender of an answer clear, and a mail has exactly
one Bereich in which it becomes a ticket.

Test: A unit test adds a second Postfach to a Bereich and expects 409.

---
id: "002720"
title: A Bereich has at most one Postfach
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_a_second_postfach_of_a_bereich_is_409"
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_create_stores_the_postfach_and_returns_no_password"
  - "frontend/src/app/pages/admin/help-tickets/help-tickets.component.spec.ts:HelpTicketsComponent"
implementation:
  - backend/app/modules/tickets/mailbox.py
  - backend/app/modules/tickets/models.py
  - backend/migrations/versions/d2f6b9a41c37_ticket_mailbox.py
  - frontend/src/app/pages/admin/help-tickets/help-tickets.component.ts
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

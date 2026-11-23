---
id: "002712"
title: The team creates a ticket by hand
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_ticket_by_hand_names_one_known_account"
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_ticket_by_hand_outside_the_own_bereiche_is_403"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_send.py:test_a_ticket_by_hand_for_an_address_needs_a_postfach_and_sends_the_message"
  - "frontend/src/app/pages/tickets/ticket-new-dialog.component.spec.ts:TicketNewDialogComponent"
implementation:
  - backend/app/modules/tickets/service.py
  - backend/app/modules/tickets/router.py
  - frontend/src/app/pages/tickets/ticket-new-dialog.component.ts
  - mcp/antragsplattform_mcp/tools/tickets.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The team creates a ticket by hand

A person with the work right in a Bereich must be able to create a ticket there for an account
or for an e-mail address. For an address the Bereich must have a Postfach, and the first public
message must go out as a mail (002733).

Reason: A case often starts with a call or a talk, and the team must be able to write to a
person first.

Test: A unit test creates a ticket for an address in a Bereich without a Postfach and expects
422.

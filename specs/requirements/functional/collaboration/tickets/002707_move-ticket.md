---
id: "002707"
title: A ticket can move to a different Bereich
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_a_move_clears_the_kategorie_and_the_foreign_assignee"
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_a_move_keeps_the_assignee_with_the_right_and_drops_the_kind"
implementation:
  - backend/app/modules/tickets/service.py
  - frontend/src/app/pages/tickets/ticket-detail.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A ticket can move to a different Bereich

A person with the work right in the Bereich of a ticket must be able to move the ticket to each
other Bereich. The move must clear the Kategorie. The move must clear the assignee when the
assignee has no work right in the new Bereich. The move must write an event with both Bereiche.

Reason: A mail often reaches the wrong team. The person who sees that must be able to pass the
ticket on, also to a Bereich that the person cannot read.

Test: A unit test moves an assigned ticket to a Bereich where the assignee has no right and
expects no assignee and one event.

---
id: "002700"
title: Each ticket belongs to one Bereich
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_a_ticket_cannot_be_without_a_bereich"
implementation:
  - backend/app/modules/tickets/models.py
  - backend/app/modules/tickets/areas.py
  - backend/migrations/versions/e41b7d90a6c2_ticket_areas.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# Each ticket belongs to one Bereich

Each ticket must belong to exactly one Bereich. A Bereich must have a name that is unique on the
platform.

Reason: A general ticket system holds the work of more than one team. The Bereich is the unit
that separates the tickets, the rights and the settings of the teams.

Test: A unit test creates a ticket without a Bereich and expects a refusal.

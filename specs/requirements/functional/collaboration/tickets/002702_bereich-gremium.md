---
id: "002702"
title: A Bereich belongs to one Gremium or to no Gremium
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_create_refuses_a_used_name_an_unknown_gremium_and_bad_kategorien"
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_plattform_keeps_its_name_its_kategorien_and_takes_the_switch"
implementation:
  - backend/app/modules/tickets/models.py
  - backend/app/modules/tickets/schemas.py
  - backend/app/modules/tickets/areas.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A Bereich belongs to one Gremium or to no Gremium

A Bereich must name at most one Gremium as its owner. The Bereich `Plattform` must have no
Gremium.

Reason: The owner decides who works in the Bereich (002703). The tickets on the platform are the
work of the platform team and not of a Gremium.

Test: A unit test saves a Bereich with two Gremien and expects 422.

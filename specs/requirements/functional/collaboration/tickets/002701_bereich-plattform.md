---
id: "002701"
title: The Bereich Plattform takes the reports of the help menu
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_a_report_of_the_help_menu_lands_in_plattform"
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_delete_refuses_a_bereich_with_a_ticket"
  - "backend/tests/integration/modules/tickets/test_ticket_areas_api.py:test_the_migration_seeds_plattform_and_every_report_lands_there"
implementation:
  - backend/app/modules/tickets/models.py
  - backend/app/modules/tickets/service.py
  - backend/app/modules/tickets/areas.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The Bereich Plattform takes the reports of the help menu

The platform must have the built-in Bereich `Plattform`. A report from the help menu without a
chosen Bereich must become a ticket of `Plattform`. An admin must not be able to delete
`Plattform`.

Reason: The reports on the platform itself need a place that exists on every installation
(000150).

Test: A unit test sends a report from the help menu and expects the ticket in `Plattform`. A
second test deletes `Plattform` and expects 409.

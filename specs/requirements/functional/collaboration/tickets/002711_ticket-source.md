---
id: "002711"
title: A ticket names its source
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_report_of_the_help_menu_has_the_source_help"
  - "backend/tests/unit/modules/tickets/test_ticket_waiting.py:test_a_ticket_by_hand_has_the_source_team_and_a_first_message"
implementation:
  - backend/app/modules/tickets/models.py
  - backend/app/modules/tickets/service.py
  - frontend/src/app/pages/tickets/ticket-detail.component.html
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A ticket names its source

A ticket must store its source: the help menu, a mail, or a person of the team. The detail view
of the team must show the source.

Reason: The source decides how an answer reaches the sender: in the app, or as a mail (002733).

Test: A unit test creates one ticket on each way and expects the three sources.

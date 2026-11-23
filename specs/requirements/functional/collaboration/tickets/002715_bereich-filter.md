---
id: "002715"
title: The ticket list shows the Bereiche of the person
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_areas.py:test_the_list_and_the_counts_keep_to_the_bereiche"
implementation:
  - backend/app/modules/tickets/service.py
  - backend/app/modules/tickets/router.py
  - frontend/src/app/pages/tickets/tickets.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The ticket list shows the Bereiche of the person

The ticket list of the team must show only the tickets of the Bereiche in which the person has
the work right. The list must have a filter for the Bereich. The filter must show only when the
person works in more than one Bereich.

Reason: A person of two teams needs one list, and a person of one team needs no control without
a choice.

Test: A unit test lists the tickets with the right in one of two Bereiche and expects only the
tickets of that Bereich.

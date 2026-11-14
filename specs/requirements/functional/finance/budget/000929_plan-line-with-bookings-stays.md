---
id: "000929"
title: The line of a Kostenstelle with bookings is not removed
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_line_with_bookings_is_not_removed"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
  - mcp/antragsplattform_mcp/tools
---

# The line of a Kostenstelle with bookings is not removed

The removal of a line from a draft version (000819) must answer 409
`plan_line_has_bookings` while the Kostenstelle of the line has a booking in the fiscal year
of the plan, and must change nothing. The Ansatz of that line can still be set to 0. The
plan page must tell the person to set the Ansatz to 0 instead.

Reason: A Nachtrag that removes the line takes the Kostenstelle out of the Haushaltsplan of
the year, and its bookings then stand on a Kostenstelle without a Titel in the plan. With
an Ansatz of 0 the Kostenstelle stays in the plan, and the plan shows that more was spent
than planned.

Test: The integration test books on a Kostenstelle of a plan in force, adds a Nachtrag and
reads the 409 for the removal of that line. It sets the Ansatz of the line to 0 and removes
the line of a Kostenstelle without a booking.

---
id: "000990"
title: A past fiscal year that is not closed takes a booking with a date in the year
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/budget/test_budget_tree_rules.py:test_a_past_year_takes_a_late_booking_with_a_date_in_the_year"
  - "backend/tests/integration/modules/budget/test_budget_tree_service.py:test_a_past_open_year_takes_a_booking_with_a_date_in_the_year"
  - "frontend/src/app/pages/budget/budget-year-select/budget-year-select.component.spec.ts:dateFitsBudgetYear"
implementation:
  - backend/app/modules/budget/tree_rules.py
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/fiscal_years.py
  - frontend/src/app/pages/budget/budget-year-select/budget-year-select.util.ts
  - frontend/src/app/pages/expenses/expense-dialogs.state.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages
---

# A past fiscal year that is not closed takes a booking with a date in the year

A fiscal year that has ended and is not closed must take a new booking and a new transfer.
The booking must carry a payment date, or else an invoice date, that lies in the year. The
transfer must carry a payment date that lies in the year. Without such a date the server must
answer 422 `booking_date_outside_year`. In a Haushalt with a plan, the plan of the year must
be in force, as for each year (000879).

The form of a booking and of a transfer must list the past years that are not closed in the
field of Haushalt and Haushaltsjahr. The current year stays preselected. For a past year the
form must ask for the payment date and must say that the date must lie in the year. The
assignment of an Antrag and the action of the flow must not take a past year. A booking
without a fiscal year takes the current year, never a past one.

Reason: A payment of the last weeks of a year is often entered after the year has ended.
Before the close of the year, the books of the year must still take it. The date is the only
sign that the money belongs to the past year, so a booking without it goes into the current
year.

Test: Unit test of the rule for the year and for the date. Integration test: the pairs for a
booking list the past year, a booking and a transfer without a date in the year are refused,
with such a date they are booked, and a closed year refuses them. Unit test of the date check
of the form.

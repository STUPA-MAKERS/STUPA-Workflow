---
id: "000879"
title: A person chooses Haushalt and Haushaltsjahr before the Kostenstelle
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/budget/test_budget_tree_rules.py:test_a_year_is_choosable_when_it_is_open_not_past_and_decided"
  - "backend/tests/integration/modules/budget/test_budget_tree_service.py:test_a_new_booking_takes_only_a_year_that_is_not_past"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_haushalt_with_a_plan_takes_a_booking_only_on_a_plan_in_force"
  - "frontend/src/app/pages/budget/budget-year-select/budget-year-select.component.spec.ts:BudgetYearSelectComponent"
implementation:
  - backend/app/modules/budget/tree_rules.py
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/modules/flow/extras_dispatcher.py
  - frontend/src/app/pages/budget/budget-year-select/budget-year-select.component.ts
scope:
  - backend/app/modules/budget
  - backend/app/modules/flow
  - frontend/src/app/pages
---

# A person chooses Haushalt and Haushaltsjahr before the Kostenstelle

Where a person chooses a Kostenstelle for a booking, a transfer or the assignment of an
Antrag, the form must first ask for one pair of a Haushalt and a Haushaltsjahr in one
field, for example "VS-Mittel 2026/27". The Kostenstelle is choosable only after that,
and only from that Haushalt. A booking from an invoice uses the booking form.

A Haushalt with a plan must be choosable with each year that is not past, not closed
and whose plan is in force. A Haushalt without a plan must be choosable with each year
that is not past and not closed. The current Haushaltsjahr must be preselected. With
more than one Haushalt, the Haushalt that the person chose last comes first, else the
first one.

The server must refuse a new booking, a new transfer and an assignment with any other
year with the code `fiscal_year_not_choosable`. A transfer stays inside one pair. A
booking or an assignment that exists in a past year stays readable and stays as it is,
and a booking that moves to another Kostenstelle keeps its year. The action of the flow
that assigns a Kostenstelle takes the current year and does nothing when the Haushalt
has no current year that is choosable.

Reason: Money moves on a decided Haushaltsplan of a year. A Kostenstelle alone does not
say which year a booking belongs to, and a booking into a year without a plan in force
would spend money that no Gremium decided.

Test: Unit test of the rule for one year. Integration tests: the pairs of a Haushalt
without a plan and with a plan; a booking into a past year and into a year without a
plan in force is refused; a booking without a year takes the current one. Component
test: the field lists the pairs and preselects the current year.

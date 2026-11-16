---
id: "001030"
title: An Antrag takes only a Kostenstelle on the expense side
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_income_nodes_are_the_nodes_below_an_income_titel"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_antrag_is_not_assigned_to_an_income_cost_centre"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_antrag_does_not_move_into_a_year_where_its_cost_centre_is_income"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_form_options_leave_out_income_cost_centres"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_tree_names_the_years_where_a_node_is_income"
  - "backend/tests/unit/modules/flow/test_flow_extras_dispatcher.py:test_assign_budget_skips_an_income_cost_centre"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre.util.spec.ts:CostCentreUtil"
  - "frontend/src/app/pages/budget/cost-centre-select/cost-centre-select.component.spec.ts:CostCentreSelectComponent"
implementation:
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/applications.py
  - backend/app/modules/budget/tree/view.py
  - backend/app/modules/budget/form_options.py
  - backend/app/modules/flow/extras_dispatcher.py
  - frontend/src/app/pages/budget/cost-centre/cost-centre.util.ts
  - frontend/src/app/pages/budget/cost-centre-select/cost-centre-select.component.ts
  - frontend/src/app/pages/applications/applications-detail.component.html
scope:
  - backend/app/modules/budget
  - backend/app/modules/flow
  - frontend/src/app/pages/budget
  - frontend/src/app/pages/applications
---

# An Antrag takes only a Kostenstelle on the expense side

A Kostenstelle is income in a Haushaltsjahr when the plan version in force of that year
puts its Titel on the side `income` (000853). Every other Kostenstelle is on the expense
side, also each one of a Haushalt without a plan. An Antrag must take only a Kostenstelle
on the expense side.

- The dialog that assigns a Kostenstelle to an Antrag must not offer a Kostenstelle that
  is income in the chosen Haushaltsjahr (000879).
- A form field of the type `budget_select` (Antrag form, capture on behalf, edit) must not
  offer a Kostenstelle that is income in the current Haushaltsjahr of its Haushalt. The
  current year is the year that the flow action takes (000879).
- The server must refuse the assignment of an income Kostenstelle with 422
  `cost_centre_income`. It must refuse the move of an Antrag into a year where its
  Kostenstelle is income with the same code.
- The flow actions that assign a Kostenstelle must do nothing when the Kostenstelle is
  income in the year that they take.

An Antrag that already has an income Kostenstelle must keep it, stay readable and show it.
The filter "Kostenstelle" of the Antrag list must still offer every Kostenstelle, because
it only finds Anträge. The pickers of the flow editor must still offer every Kostenstelle,
because the flow action checks the side when it runs.

Reason: An Antrag asks for money to spend. An income Titel holds money that comes in, so
an Antrag on it would spend from a Titel that the plan has no Ansatz to spend for.

Test: Unit test of the income nodes of a version. Integration tests: an assignment and a
move of the year to an income Kostenstelle are refused; the form options and the tree name
the income Kostenstellen; the flow action skips one. Component test: the picker leaves out
an income Kostenstelle of the chosen year.

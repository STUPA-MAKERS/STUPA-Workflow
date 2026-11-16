---
id: "001031"
title: An Antrag takes only a Kostenstelle without a Kostenstelle below it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_antrag_is_not_assigned_to_a_cost_centre_with_children"
  - "backend/tests/unit/modules/flow/test_flow_extras_dispatcher.py:test_assign_budget_skips_a_cost_centre_with_children"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre.util.spec.ts:CostCentreUtil"
  - "frontend/src/app/pages/budget/cost-centre-select/cost-centre-select.component.spec.ts:CostCentreSelectComponent"
implementation:
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/applications.py
  - backend/app/modules/flow/extras_dispatcher.py
  - frontend/src/app/pages/budget/cost-centre-select/cost-centre-select.component.ts
  - frontend/src/app/shared/formly/types/formly-budget-select.type.ts
  - frontend/src/app/pages/applications/applications-detail.component.html
scope:
  - backend/app/modules/budget
  - backend/app/modules/flow
  - frontend/src/app/pages/budget
  - frontend/src/app/pages/applications
  - frontend/src/app/shared/formly
---

# An Antrag takes only a Kostenstelle without a Kostenstelle below it

An Antrag must take only a leaf: a Kostenstelle that has no active Kostenstelle below it. A
Haushalt and a Titel with Kostenstellen below them are no leaf.

- The dialog that assigns a Kostenstelle to an Antrag and a form field of the type
  `budget_select` must still show every node that 001030 offers, so the tree stays
  readable. A node that is no leaf must not be choosable: the list shows it without the
  check mark and as not available (`aria-disabled`), and a press or the keyboard skips it.
- The server must refuse the assignment of a Kostenstelle that is no leaf with 422
  `cost_centre_not_leaf`.
- The flow actions that assign a Kostenstelle must do nothing when the Kostenstelle is no
  leaf.

An Antrag that already has a Kostenstelle with Kostenstellen below it must keep it, stay
readable, show it and move into another year. The filter "Kostenstelle" of the Antrag list
and the pickers of the flow editor must still offer every Kostenstelle (001030).

Reason: The money of an Antrag must land on the Kostenstelle where it is spent. A Haushalt or
a Titel with Kostenstellen below it only sums them up, so an Antrag on it hides which
Kostenstelle pays.

Test: Integration test: an assignment to a Titel with Kostenstellen below it is refused, an
assignment to its leaf is taken. Unit test: the flow action skips a node with children.
Component tests: the picker shows a node with children as not choosable, and a press and
the keyboard skip it.

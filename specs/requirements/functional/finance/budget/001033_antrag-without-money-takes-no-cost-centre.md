---
id: "001033"
title: An Antrag of a type without money takes no Kostenstelle
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_antrag_without_money_takes_no_cost_centre"
  - "backend/tests/unit/modules/budget/test_budget_tree_service_unit.py:test_assign_budget_refuses_an_antrag_without_money"
  - "backend/tests/unit/modules/flow/test_flow_extras_dispatcher.py:test_assign_budget_skips_an_antrag_without_money"
  - "frontend/src/app/pages/applications/applications-detail.header.spec.ts:ApplicationsDetailComponent"
implementation:
  - backend/app/modules/application_types/service.py
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/applications.py
  - backend/app/modules/flow/extras_dispatcher.py
  - frontend/src/app/pages/applications/applications-detail.component.ts
  - frontend/src/app/pages/applications/applications-detail.component.html
scope:
  - backend/app/modules/application_types
  - backend/app/modules/budget
  - backend/app/modules/flow
  - frontend/src/app/pages/applications
---

# An Antrag of a type without money takes no Kostenstelle

An Antragsart without the flag "Mit Budget" (`has_budget` false) asks for no money, for
example "IT-Zugang" or "Nicht-monetärer Antrag". An Antrag of such a type must not take a
Kostenstelle.

- The Antrag detail must not show the row "Kostenstelle" and must not offer "Zuordnen"
  for such an Antrag.
- The server must refuse the assignment of a Kostenstelle to such an Antrag with 422
  `application_without_budget`. This holds for the route and for the MCP tool, which
  uses the route.
- The flow actions that assign a Kostenstelle (`assignBudget`, `assignBudgetFromField`,
  `assignBudgetFromApplicantGremium`, `assignBudgetFromMap`) must do nothing for such an
  Antrag.

An Antrag that already has a Kostenstelle keeps it and shows it. Its row offers only
"Entfernen", and the server accepts the removal. This case occurs when an admin removes
the flag from a type that already has Anträge with a Kostenstelle.

Reason: A Kostenstelle holds money. An Antrag without an amount has nothing to spend from
it, so an assignment only adds a wrong Antrag to the list of the Kostenstelle.

Test: Integration test: the assignment is refused and an old assignment can be removed.
Unit tests: the service refuses the assignment, the flow action skips it. Component test:
the detail shows no row, and for an old assignment only "Entfernen".

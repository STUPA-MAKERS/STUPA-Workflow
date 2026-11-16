---
id: "000841"
title: A request that records a step names the step
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_request_passes_only_the_step_it_names"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_step_route_passes_the_named_step"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "mcp/antragsplattform_mcp/tests/test_budget_plan_tools.py:test_a_step_is_named_and_a_vote_finds_its_plan"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - mcp/antragsplattform_mcp/tools/budget_plan.py
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget/plan
  - mcp/antragsplattform_mcp
---

# A request that records a step names the step

The request that records a step as passed (000825) can name the step by its place, from 0
(`step`). When the named step is not the next step of the version, the request must answer
409 `plan_step_not_next`. The plan page and the MCP tool must name the step that the person
saw. A request without `step` must record the next step.

Reason: Two people can press "Schritt abschließen" for the same step at the same moment.
Without the name the second request records the step after it, which nobody confirmed.

Test: The tests record a step twice with the same place and read the refusal, and read the
request of the plan page and of the MCP tool.

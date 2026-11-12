---
id: "000823"
title: A budget holds the steps of its Haushaltsplan
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A budget holds the steps of its Haushaltsplan

A top-level Kostenstelle with the plan switch on must hold an ordered list of plan steps.
Each step must have a name and can name one Gremium. A person with `budget.structure`
must set the list (`PUT /budgets/{id}/plan-steps`). The list can be empty and must hold at
most 10 steps. The platform must give no default steps.

Reason: The law of each budget says which body decides its plan and which body approves
it. The VS-Mittel need the decision of the STUPA and the approval of the Präsidium, a
different budget needs different steps.

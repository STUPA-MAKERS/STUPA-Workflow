---
id: "000825"
title: A person records a passed step
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A person records a passed step

A person with `budget.structure` must record the next step of a version as passed
(`POST /budget-plan-versions/{id}/steps/next`). The first step must answer 422
`plan_not_balanced` for a version that is not balanced (000795). The record must write an
audit entry with the name of the step and its Gremium.

Reason: A decision can happen outside the platform, for example the approval of the
Präsidium, so a person must be able to record it.

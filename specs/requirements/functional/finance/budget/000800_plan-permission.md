---
id: "000800"
title: A plan write needs budget.structure
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A plan write needs budget.structure

Each write to a Haushaltsplan, a version or a line must need the permission
`budget.structure`. A read must follow the read rule of the Kostenstelle.

Reason: The persons who manage the Kostenstellen and the fiscal years also write the plan.

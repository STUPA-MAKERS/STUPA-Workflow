---
id: "000824"
title: A version keeps the steps it started with
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A version keeps the steps it started with

When a version leaves `draft`, the platform must copy the steps of its budget into the
version. A later change of the steps of the budget must not change a version that left
`draft`. The plan read must give the steps of each version with the time of each passed
step, and for a `draft` the steps of the budget.

Reason: A decided plan is a record of the steps that applied when it was decided.

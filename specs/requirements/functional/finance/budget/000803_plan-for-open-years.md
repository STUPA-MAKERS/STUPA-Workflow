---
id: "000803"
title: Each open fiscal year gets a Stammplan from its allocations
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# Each open fiscal year gets a Stammplan from its allocations

The migration must give each open fiscal year a Stammplan in the state `in_force`. The
Ansatz of each line must equal the allocation of its Kostenstelle. A closed fiscal year must
not get a Haushaltsplan.

Reason: A current year needs the plan for a Nachtrag. A closed year does not change.

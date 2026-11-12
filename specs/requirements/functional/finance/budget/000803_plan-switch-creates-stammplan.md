---
id: "000803"
title: The plan switch gives each open fiscal year a Stammplan
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# The plan switch gives each open fiscal year a Stammplan

When a person sets the plan switch (000814) of a top-level Kostenstelle to on, the system
must give each open fiscal year of that Kostenstelle a Stammplan in the state `in_force`.
The Ansatz of each line must equal the allocation of its Kostenstelle. A closed fiscal year
must not get a Haushaltsplan.

Reason: A current year needs the plan for a Nachtrag. A closed year does not change.

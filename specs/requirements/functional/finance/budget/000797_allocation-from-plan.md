---
id: "000797"
title: The plan in force sets the allocations
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# The plan in force sets the allocations

When a version comes into force, the platform must write the allocation of each Kostenstelle
from the Ansatz of its line. A Kostenstelle without a line must get the allocation 0 €.

Reason: The allocation and the approved plan must show the same amounts.

---
id: "000814"
title: A top-level Kostenstelle has a plan switch
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A top-level Kostenstelle has a plan switch

A top-level Kostenstelle must have the switch "Haushaltsplan". The switch must be off for a
new and for an existing Kostenstelle. The rules for a Haushaltsplan must apply only to a
Kostenstelle below a top-level Kostenstelle with the switch on. The change of the switch
needs `budget.structure`.

Reason: QS-Mittel are no budget of the Studierendenschaft. The Rektorat gives them on a
proposal of the STUPA (QualSiG § 1 (2)), so LHO § 106 and § 108 do not apply to them.

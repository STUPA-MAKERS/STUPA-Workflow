---
id: "000794"
title: A plan line holds the Ansatz of one Kostenstelle
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A plan line holds the Ansatz of one Kostenstelle

A plan version must have at most one line for each Kostenstelle below the top level. A line
must hold an Ansatz from 0 € and an optional Erläuterung. The sum of the Ansätze of the
children must not exceed the Ansatz of the parent, else 422.

Reason: LHO § 17 tells the Studierendenschaft to plan each purpose apart and to explain it.

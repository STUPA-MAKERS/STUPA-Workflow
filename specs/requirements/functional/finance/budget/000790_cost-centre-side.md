---
id: "000790"
title: A Kostenstelle below the top level has a side
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A Kostenstelle below the top level has a side

A Kostenstelle below the top level must have the side `income` or `expense`. A child must
have the side of its parent. A top-level Kostenstelle must not have a side.

Reason: LHO § 15 tells the Studierendenschaft to plan income and expenses apart and in full.

---
id: "000796"
title: One version of a plan is in force
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# One version of a plan is in force

A Haushaltsplan must have at most one version in the state `in_force`. When a version
comes into force, the platform must set the earlier version in force to `replaced`.

Reason: Only one plan applies at one time.

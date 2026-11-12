---
id: "000799"
title: A Nachtrag starts as a copy of the version in force
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A Nachtrag starts as a copy of the version in force

A new Nachtrag must start in `draft` with a copy of the lines of the version in force. A
Haushaltsplan must have at most one version before `in_force` at one time, else 409
`plan_draft_exists`.

Reason: Two open versions make it unclear which one the STUPA decides.

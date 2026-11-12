---
id: "000793"
title: Only a draft version can be edited
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# Only a draft version can be edited

The lines of a plan version must be editable only in the state `draft`. A write to the
lines of a version in a different state must answer 409 `plan_version_locked`.

Reason: A decided version must stay the text that the STUPA decided.

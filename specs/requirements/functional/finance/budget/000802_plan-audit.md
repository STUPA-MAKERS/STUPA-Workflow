---
id: "000802"
title: Each plan state change is audited
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# Each plan state change is audited

The platform must write an audit entry for each new version, each state change of a version
and each change of a line. The entry must name the Haushaltsplan, the version and the actor.

Reason: An examiner must be able to see who changed the plan and when.

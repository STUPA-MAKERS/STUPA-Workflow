---
id: "000915"
title: An objection ends an Umlaufverfahren
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# An objection ends an Umlaufverfahren

Each eligible member must be able to object to an open circular vote (000914). The first
objection must cancel the vote with the reason `objection`. The audit log must record who
objected.

Reason: The Umlaufverfahren is valid only when no member objects to the procedure.

Test: An integration test that objects to an open circular vote.

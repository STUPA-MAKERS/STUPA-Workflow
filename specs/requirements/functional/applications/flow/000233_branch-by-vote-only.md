---
id: "000233"
title: Only the vote result fires a vote branch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/voting
---

# Only the vote result fires a vote branch

A transition with the branch `pass` or `fail` fires only from the result of a vote. A manual
fire of a branch transition or of an automatic transition gives 409.

Reason: Nobody can set a vote result by hand.

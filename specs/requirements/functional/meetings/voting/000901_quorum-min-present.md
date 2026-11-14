---
id: "000901"
title: A Gremium can need a least number of present members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/gremien
  - backend/app/modules/admin
  - backend/app/modules/voting
  - frontend/src/app/pages/admin
---

# A Gremium can need a least number of present members

A Gremium must have the optional setting `quorumMinPresent`. When the value is set, a meeting
vote must meet its quorum only if at least that number of roster persons is present.

Reason: The AStA decides only when at least three of its members are present.

Test: An integration test with a Gremium that has `quorumMinPresent`.

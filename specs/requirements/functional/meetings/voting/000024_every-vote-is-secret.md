---
id: F/meetings/voting/000024
title: Every vote is secret
kind: functional
status: draft
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
owner: frederikbeimgraben
updated: 2026-11-05
---

# Every vote is secret

Every motion, election and poll must be secret. The API must refuse `secret: false` with 422
`open_vote_unavailable`. The UI must not show a switch for open votes.

Reason: An open ballot shows how each member voted.

Test: `backend/tests/unit/modules/voting/`

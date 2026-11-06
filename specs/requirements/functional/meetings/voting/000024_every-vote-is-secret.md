---
id: "000024"
title: Every vote is secret
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# Every vote is secret

Every motion, election and poll must be secret. The API must refuse `secret: false` with 422
`open_vote_unavailable`. The UI must not show a switch for open votes.

Reason: An open ballot shows how each member voted.

Test:
`backend/tests/unit/modules/voting/test_vote_create_gremium_only.py:test_create_open_vote_422`.

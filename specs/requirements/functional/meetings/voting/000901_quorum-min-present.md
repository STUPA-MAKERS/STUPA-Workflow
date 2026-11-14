---
id: "000901"
title: A Gremium can need a least number of present members
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/voting/test_voting_tally.py:test_least_number_of_present_persons"
  - "backend/tests/integration/modules/livevote/test_quorum_present.py:test_close_needs_the_least_number_of_present_members"
implementation:
  - backend/app/modules/gremien/models.py
  - backend/app/modules/livevote/vote_build.py
  - backend/app/modules/voting/tally.py
  - frontend/src/app/pages/admin/committees/gremium-dialog/gremium-dialog.component.html
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

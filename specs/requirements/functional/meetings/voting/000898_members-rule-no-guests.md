---
id: "000898"
title: A vote with a members rule has no guest ballots
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/voting/test_voting_tally.py:test_members_rule_with_guests_is_refused"
  - "backend/tests/integration/modules/livevote/test_quorum_present.py:test_members_rule_refuses_guest_ballots"
implementation:
  - backend/app/shared/config_schemas.py
  - backend/app/modules/livevote/vote_build.py
scope:
  - backend/app/modules/voting
  - backend/app/shared
  - backend/app/modules/livevote
---

# A vote with a members rule has no guest ballots

The server must refuse a vote that has a members rule together with `guestsVote`. The answer
must be 422 `guests_vote_unavailable`.

Reason: A guest is not a member, so a guest ballot cannot count against the number of members.

Test: A unit test of the `VoteConfig` validator.

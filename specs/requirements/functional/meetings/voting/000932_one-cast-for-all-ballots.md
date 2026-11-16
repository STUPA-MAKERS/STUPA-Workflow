---
id: "000932"
title: One cast counts for the own ballot and all represented ballots
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/delegations/test_delegate_limit_live.py:test_one_cast_writes_the_own_and_each_represented_ballot"
  - "backend/tests/unit/modules/voting/test_voting_service_unit.py:test_cast_own_ballot_counts_for_each_represented_member"
  - "frontend/src/app/features/voting/ballot/ballot.component.spec.ts:BallotComponent"
implementation:
  - backend/app/modules/voting/service
  - backend/app/modules/delegations/service.py
  - backend/app/modules/livevote/service/votes.py
  - frontend/src/app/features/voting/ballot/ballot.component.ts
scope:
  - backend/app/modules/voting
  - backend/app/modules/delegations
  - backend/app/modules/livevote
  - frontend/src/app/features/voting
  - frontend/src/app/features/meetings
---

# One cast counts for the own ballot and all represented ballots

A person with voting delegations must cast one choice for a vote. The cast must write the own
ballot and one ballot for each delegator, all with this choice. A person without an own ballot
must cast one choice for all represented members. A separate delegation ballot must answer 409
`vote_as_unit` while the own ballot of the person is open. The ballot must show the number of
voting rights that the cast exercises, and the names of the represented members.

Reason: A member with transferred votes must vote in unity. A secret ballot has no link to its
voter, so the server cannot compare two separate casts.

Test: An integration test that casts once with two delegations and counts three ballots.

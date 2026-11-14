---
id: "000900"
title: The quorum of a meeting vote counts the present members
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/unit/modules/voting/test_voting_tally.py:test_quorum_counts_the_present_persons_and_not_the_ballots"
  - "backend/tests/integration/modules/livevote/test_quorum_present.py:test_close_meets_the_quorum_by_present_members"
implementation:
  - backend/app/modules/voting/tally.py
  - backend/app/modules/voting/service.py
  - backend/app/modules/livevote/service/votes.py
  - backend/app/modules/delegations/pool_seat.py
scope:
  - backend/app/modules/voting
  - backend/app/modules/meetings
  - backend/app/modules/livevote
---

# The quorum of a meeting vote counts the present members

A meeting vote with a quorum must compare the present persons of the roster with the eligible
count. A person is present with the attendance status `present` or with a pool seat (000113). A
ballot of a delegation must not count. A vote without a meeting must count the ballots.

Reason: The Organisationssatzung defines the Beschlussfähigkeit by the members who are present,
and it excludes transferred votes.

Test: An integration test that closes a meeting vote with few ballots and enough present
members.

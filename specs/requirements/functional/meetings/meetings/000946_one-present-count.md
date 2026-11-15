---
id: "000946"
title: A meeting shows one count of present members
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - backend/tests/integration/modules/delegations/test_one_present_count.py:test_the_head_the_vote_and_the_protocol_show_one_count
  - backend/tests/integration/modules/delegations/test_one_present_count.py:test_the_close_fixes_the_count
  - backend/tests/unit/modules/meetings/test_present.py:test_a_person_counts_one_time_and_only_with_a_voting_right
  - frontend/src/app/shared/present-count.util.spec.ts:presentCount
implementation:
  - backend/app/modules/meetings/present.py
  - backend/app/modules/livevote/service/votes.py
  - frontend/src/app/shared/present-count.util.ts
scope:
  - backend/app/modules/livevote
  - backend/app/modules/meetings
  - backend/app/modules/protocol
  - frontend/src/app/features/meetings
---

# A meeting shows one count of present members

The head of a meeting, its attendance list, its votes and its protocol must show the same
count of present members. This count must be the count of the quorum (000900): each eligible
member with the attendance status `present` and each pool seat (000113). A person must count
one time only. A member without a voting right, a former member and a guest must not count.
The close of a meeting must fix this count and the number of the members with a voting right.
A closed meeting must show the fixed values.

Reason: The Beschlussfähigkeit knows one count. Different counts on one page raise questions
in the Sitzung.

Test: A backend integration test reads the count of a meeting with a present member without a
voting right, a present former member and a pool seat from the head, the vote and the protocol
and finds one value.

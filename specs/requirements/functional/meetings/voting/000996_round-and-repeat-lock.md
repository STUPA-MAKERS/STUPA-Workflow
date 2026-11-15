---
id: "000996"
title: The next Wahlgang and the repeat of an election lock each other
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/voting/test_election_next_round_unit.py:test_an_election_that_is_voted_on_again_takes_no_next_round"
  - "backend/tests/integration/modules/livevote/test_election_next_round.py:test_three_rounds_then_the_lot"
implementation:
  - backend/app/modules/voting/election.py
  - backend/app/modules/livevote/vote_repeat.py
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.ts
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# The next Wahlgang and the repeat of an election lock each other

A Wahlgang of an election (000971) must have only one vote that continues it: its next
Wahlgang or its repeat.

1. A Wahlgang with a repeat that is not cancelled must take no next Wahlgang. The server must
   answer 409 `repeat_exists`.
2. A Wahlgang with a next Wahlgang that is not cancelled must take no repeat. The server must
   answer 409 `next_round_exists`.
3. The page must offer only the step that the server takes.

Reason: With both, one election has two lines of Wahlgänge with two results, and the
protocol cannot say which person is elected.

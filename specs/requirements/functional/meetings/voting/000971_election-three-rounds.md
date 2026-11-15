---
id: "000971"
title: An election by the majority of the members has up to three Wahlgänge
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/voting/test_election_rounds.py:test_third_round_takes_the_simple_majority"
  - "backend/tests/unit/modules/voting/test_election_rounds.py:test_third_round_tie_goes_to_the_lot"
  - "backend/tests/unit/modules/voting/test_election_rounds.py:test_two_strongest_stand_in_the_third_round"
  - "backend/tests/integration/modules/livevote/test_election_next_round.py:test_three_rounds_then_the_lot"
implementation:
  - backend/app/modules/voting/tally.py
  - backend/app/modules/voting/election.py
  - backend/app/modules/voting/router.py
  - backend/app/modules/protocol/markdown.py
  - frontend/src/app/features/voting/election-result/election-result.component.ts
scope:
  - backend/app/modules/voting
  - backend/app/modules/protocol
  - frontend/src/app/features/voting
  - frontend/src/app/features/meetings
---

# An election by the majority of the members has up to three Wahlgänge

This spec applies to an election with the rule `members_majority` (000912).

1. In the first and in the second Wahlgang, a candidate must be elected only with more votes
   than half of the eligible count. Without such a candidate the result must be `no_majority`.
2. After a first or a second Wahlgang with the result `no_majority`, the result must show the
   button "Zweiter Wahlgang" or "Dritter Wahlgang". The button must create the next Wahlgang
   as a draft on the same agenda item. The protokollant opens it (000028). An election must
   have only one next Wahlgang, and there must be no fourth Wahlgang.
3. The second Wahlgang must have the candidates of the first Wahlgang.
4. In the third Wahlgang, the simple majority must be sufficient: the candidate with the most
   votes is elected. With one candidate, more "Ja" than "Nein" elect the candidate.
5. If the second Wahlgang had more than two candidates, only the two candidates with the most
   votes in the second Wahlgang must stand in the third Wahlgang.
6. If a tie in the second Wahlgang leaves a place in the third Wahlgang open, the platform
   must draw the lot among the tied candidates for this place. The result of the second
   Wahlgang and the protocol must name this lot.
7. A tie in the third Wahlgang must be decided by lot (000027).
8. A Wahlgang that misses the quorum has the result `rejected` and gets no next Wahlgang.
9. The protocol must name the number of each Wahlgang, and the third Wahlgang must name the
   simple majority.

Reason: The Organisationssatzung says: "Erreicht bei einer Wahl, für die diese Satzung die
Mehrheit der Mitglieder verlangt, im ersten Wahlgang niemand diese Mehrheit, findet ein zweiter
Wahlgang statt. Erreicht auch darin niemand die Mehrheit der Mitglieder, genügt in einem dritten
Wahlgang die einfache Mehrheit; bei mehr als zwei Kandidierenden treten darin nur die beiden an,
die im zweiten Wahlgang die meisten Stimmen erhalten haben. Bei Stimmengleichheit im dritten
Wahlgang entscheidet das Los." The Satzung does not say who stands after a tie for the second
place. The lot is the only instrument that the Satzung names for a tie, thus rule 6 uses it.

Test: Unit tests of the tally per Wahlgang and of the candidates of the third Wahlgang, and an
integration test that runs three Wahlgänge to the lot.

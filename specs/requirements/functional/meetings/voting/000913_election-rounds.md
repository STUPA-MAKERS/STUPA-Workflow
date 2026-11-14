---
id: "000913"
title: An election without a majority goes to a second and a third round
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# An election without a majority goes to a second and a third round

After the result `no_majority` the protokollant must be able to start the next round on the
same TOP. Round 2 must have the candidates and the rule of round 1. Round 3 must have only the
two candidates with the most votes of round 2. Round 3 must elect the candidate with the most
votes, and the lot must decide a tie.

Reason: The Organisationssatzung gives these three Wahlgänge for an election that needs the
majority of the members.

Test: An integration test that runs three rounds.
